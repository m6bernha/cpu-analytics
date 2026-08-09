"""Generate XML sitemaps for every public URL on the site.

Run after preprocess.py, from the repo root:

    python data/generate_sitemap.py

Writes into frontend/public/, which Vercel serves as static files:

    sitemap.xml            the INDEX, pointing at the three below
    sitemap-core.xml       the tab views (hand-maintained list here)
    sitemap-athletes.xml   one URL per lifter in the parquet
    sitemap-meets.xml      one URL per (meet, date)

WHY THIS EXISTS
---------------
ADR 0002 Phase 1 built /athlete/{name} and /meet/{name}/{date} pages
explicitly so the site could be found through search. But the sitemap
listed six tab URLs, so the ~20k pages that carry the actual long-tail
search value ("<lifter name> powerlifting results") were reachable only by
crawling JavaScript-rendered internal links. This closes that gap.

WHY IT IS A BUILD-TIME SCRIPT, NOT AN ENDPOINT
----------------------------------------------
Serving sitemaps from the Render backend would put a free-tier cold start
(up to ~50 s) in front of a crawler that gives up in 5-10 s. Static files
on Vercel have no such failure mode. The tradeoff is that sitemaps refresh
weekly with the data rather than on demand, which matches how often the
underlying data changes anyway.

ENCODING IS LOAD-BEARING
------------------------
The path segment must byte-for-byte match what `athletePath()` /
`meetPath()` in frontend/src/lib/route.ts produce, because the slug is the
URL-encoded EXACT OpenIPF name and the round trip has to be lossless. Those
use encodeURIComponent, whose unreserved set is A-Za-z0-9 plus -_.!~*'().
Python's quote() already leaves -_.~ alone, so passing the rest as `safe`
reproduces it exactly. A mismatch here would emit URLs that 200 (the SPA
rewrite catches any /athlete/*) but render "lifter not found", which is
worse than omitting them.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
# Override to point at a parquet other than the local preprocess output --
# e.g. the live one from the data-latest release, when regenerating by hand
# on a machine whose local copy has gone stale.
PARQUET = Path(
    os.environ.get("OPENIPF_PARQUET", REPO_ROOT / "data" / "processed" / "openipf.parquet")
)
PUBLIC_DIR = REPO_ROOT / "frontend" / "public"

# Override when the custom domain lands (P6 decision). No trailing slash.
BASE_URL = os.environ.get("SITE_BASE_URL", "https://cpu-analytics.vercel.app").rstrip("/")

# The sitemap protocol caps a single file at 50,000 URLs. Chunking below that
# keeps headroom and means a future scope expansion (P7 wants global IPF, ~100x
# the rows) does not silently emit an invalid sitemap.
MAX_URLS_PER_FILE = 45_000

# Exactly the encodeURIComponent unreserved set minus what quote() already
# leaves alone. See the module docstring.
_ENCODE_URI_COMPONENT_SAFE = "!*'()"


def encode_segment(value: str) -> str:
    """Percent-encode one path segment the way encodeURIComponent does."""
    return quote(value, safe=_ENCODE_URI_COMPONENT_SAFE)


def _url_entry(loc: str, lastmod: str | None = None) -> str:
    parts = [f"    <loc>{escape(loc)}</loc>"]
    if lastmod:
        parts.append(f"    <lastmod>{lastmod}</lastmod>")
    return "  <url>\n" + "\n".join(parts) + "\n  </url>"


def _urlset(entries: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


def _sitemap_index(files: list[tuple[str, str | None]]) -> str:
    body = []
    for name, lastmod in files:
        parts = [f"    <loc>{escape(f'{BASE_URL}/{name}')}</loc>"]
        if lastmod:
            parts.append(f"    <lastmod>{lastmod}</lastmod>")
        body.append("  <sitemap>\n" + "\n".join(parts) + "\n  </sitemap>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(body)
        + "\n</sitemapindex>\n"
    )


# The app shell's tab views. These live in the query string rather than the
# path, so they cannot be derived from data the way the other two files are.
CORE_PATHS = [
    "/",
    "/?tab=rankings",
    "/?tab=projection",
    "/?tab=lookup",
    "/?tab=qt",
    "/?tab=scout",
    "/?tab=about",
]


def build_core() -> str:
    return _urlset([_url_entry(f"{BASE_URL}{p}") for p in CORE_PATHS])


def fetch_athletes(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    """(name, last meet date) for every lifter, newest activity first.

    Ordering by recency is deliberate: crawlers work a sitemap roughly in
    order, so active lifters -- the ones people actually search for -- get
    seen before a lifter whose only meet was in 2012.
    """
    return con.execute(
        """
        SELECT Name, CAST(MAX(Date) AS VARCHAR)[1:10] AS lastmod
        FROM read_parquet(?)
        WHERE Name IS NOT NULL AND TRIM(Name) <> ''
        GROUP BY Name
        ORDER BY lastmod DESC, Name
        """,
        [str(PARQUET)],
    ).fetchall()


def fetch_meets(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    """(meet name, date) for every meet. Keyed exactly as meets.py keys it."""
    return con.execute(
        """
        SELECT DISTINCT MeetName, CAST(Date AS VARCHAR)[1:10] AS d
        FROM read_parquet(?)
        WHERE MeetName IS NOT NULL AND TRIM(MeetName) <> '' AND Date IS NOT NULL
        ORDER BY d DESC, MeetName
        """,
        [str(PARQUET)],
    ).fetchall()


def write_chunked(stem: str, entries: list[str], lastmod: str | None) -> list[tuple[str, str | None]]:
    """Write entries as one file, or several numbered ones past the cap."""
    if len(entries) <= MAX_URLS_PER_FILE:
        name = f"{stem}.xml"
        (PUBLIC_DIR / name).write_text(_urlset(entries), encoding="utf-8")
        return [(name, lastmod)]

    written: list[tuple[str, str | None]] = []
    for i in range(0, len(entries), MAX_URLS_PER_FILE):
        name = f"{stem}-{i // MAX_URLS_PER_FILE + 1}.xml"
        chunk = entries[i : i + MAX_URLS_PER_FILE]
        (PUBLIC_DIR / name).write_text(_urlset(chunk), encoding="utf-8")
        written.append((name, lastmod))
    return written


def main() -> None:
    if not PARQUET.exists():
        raise SystemExit(
            f"missing {PARQUET}. Run `python data/preprocess.py` first."
        )
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    athletes = fetch_athletes(con)
    meets = fetch_meets(con)

    # Newest meet in the dataset doubles as the index lastmod: it is exactly
    # the thing that changes when a refresh brings in new results.
    newest = max(
        ([a[1] for a in athletes] or [""]) + ([m[1] for m in meets] or [""])
    ) or None

    (PUBLIC_DIR / "sitemap-core.xml").write_text(build_core(), encoding="utf-8")

    athlete_files = write_chunked(
        "sitemap-athletes",
        [
            _url_entry(f"{BASE_URL}/athlete/{encode_segment(name)}", lastmod)
            for name, lastmod in athletes
        ],
        newest,
    )
    meet_files = write_chunked(
        "sitemap-meets",
        [
            _url_entry(f"{BASE_URL}/meet/{encode_segment(name)}/{date}", date)
            for name, date in meets
        ],
        newest,
    )

    # The index keeps the filename `sitemap.xml` that robots.txt already
    # advertises and that search engines may already have on file, so this
    # upgrade costs no re-discovery.
    index_entries = [("sitemap-core.xml", None), *athlete_files, *meet_files]
    (PUBLIC_DIR / "sitemap.xml").write_text(
        _sitemap_index(index_entries), encoding="utf-8"
    )

    total = len(CORE_PATHS) + len(athletes) + len(meets)
    print(f"[sitemap] core     {len(CORE_PATHS):>6} urls")
    print(f"[sitemap] athletes {len(athletes):>6} urls -> {len(athlete_files)} file(s)")
    print(f"[sitemap] meets    {len(meets):>6} urls -> {len(meet_files)} file(s)")
    print(f"[sitemap] index    sitemap.xml ({len(index_entries)} entries)")
    print(f"[sitemap] total    {total:,} urls, newest data {newest}")


if __name__ == "__main__":
    main()
