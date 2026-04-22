"""
Federal CPU qualifying-total scraper.

Source of truth: https://www.powerlifting.ca/qualifying-standards/ (2026
current) and https://www.powerlifting.ca/2027qualifications (2027
effective Jan 1). Both publish qualifying totals as PDFs, not HTML
tables. This module:

1. Fetches both landing pages and rediscovers current PDF hrefs (they
   rotate whenever CPU revises a standard).
2. Downloads the PDFs we care about (Classic / 3-Lift only; Bench Only
   and Equipped are parsed but filtered out by the orchestrator).
3. Parses each PDF via pdfplumber's ``extract_tables()`` which returns
   an 8-column grid per page.
4. Walks the grid as a small state machine, tracking the current (year,
   level, region, equipment, event, sex) context and emitting one row
   per non-empty cell.

The parser is intentionally permissive about row order but strict about
cell contents: any QT that cannot be parsed as a float, or any
unexpected cell where one of the state-machine rules applies, raises
ValueError. The fixture tests in ``backend/tests/test_scrape_qt.py``
lock in parser output against a known-good CSV; if CPU restructures the
PDFs, those tests break before a bad CSV reaches production.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pdfplumber
import requests

log = logging.getLogger(__name__)

# Polite user-agent. CPU's Wix host is cheap to hit but we tag every
# request with a contact email so the CPU admin can reach us if the
# scraper ever misbehaves.
_USER_AGENT = "cpu-analytics-scraper/1.0 (+contact matthias.bernhard7@gmail.com)"
_HTTP_TIMEOUT = 30.0
_HTTP_RETRIES = 3
_HTTP_BACKOFF_S = 2.0

# Pages to crawl for PDF hrefs. Order matters: 2026 page first so 2026
# context gets seeded before any 2027 PDFs are processed.
CPU_LANDING_URLS = (
    "https://www.powerlifting.ca/qualifying-standards/",
    "https://www.powerlifting.ca/2027qualifications",
)

# Weight classes the parser recognises in col 0.
_WEIGHT_CLASS_RE = re.compile(r"^\d+\+?$")

# Valid age-division headers (match the 7 columns after weight-class).
_DIVISION_HEADERS = frozenset((
    "Open", "Sub-Junior", "Junior",
    "Master 1", "Master 2", "Master 3", "Master 4",
))


@dataclass
class _Context:
    """Mutable state while walking one PDF's tables."""
    effective_year: int | None = None
    level: str | None = None          # "Nationals" | "Regionals"
    region: str | None = None          # None | "Western/Central" | "Eastern"
    equipment: str | None = None       # "Classic" | "Equipped"
    event: str | None = None           # "SBD" | "B"
    sex: str | None = None             # "M" | "F"
    division_cols: list[str] = field(default_factory=list)

    def ready_for_data(self) -> bool:
        return all(v is not None for v in (
            self.effective_year, self.level, self.equipment,
            self.event, self.sex,
        )) and len(self.division_cols) == 7


def _is_blank(cell) -> bool:
    return cell is None or cell == ""


def _all_blank(row: list) -> bool:
    return all(_is_blank(c) for c in row)


def _apply_title(ctx: _Context, title: str) -> bool:
    """
    Update context based on a title/subtitle cell. Returns True if the
    title was recognised (meaning: consume the row and do not emit from
    it), False otherwise.
    """
    t = title.strip()
    tu = t.upper()

    # 2026 titles (single page bundles both Nationals and Regionals).
    if "QUALIFYING TOTAL FOR CPU UNEQUIPPED NATIONALS" in tu:
        ctx.effective_year = 2026
        ctx.level = "Nationals"
        ctx.region = None
        ctx.equipment = "Classic"
        ctx.event = "SBD"
        ctx.sex = None
        ctx.division_cols = []
        return True
    if "QUALIFYING TOTAL FOR CPU UNEQUIPPED REGIONALS" in tu:
        ctx.effective_year = 2026
        ctx.level = "Regionals"
        ctx.region = None
        ctx.equipment = "Classic"
        ctx.event = "SBD"
        ctx.sex = None
        ctx.division_cols = []
        return True

    # 2027 titles.
    if t == "National Qualifying Standards":
        ctx.effective_year = 2027
        ctx.level = "Nationals"
        ctx.region = None
        ctx.equipment = "Classic"
        ctx.event = None  # set by subtitle
        ctx.sex = None
        ctx.division_cols = []
        return True
    if t == "Western/Central Qualifying Standards":
        ctx.effective_year = 2027
        ctx.level = "Regionals"
        ctx.region = "Western/Central"
        ctx.equipment = "Classic"
        ctx.event = None
        ctx.sex = None
        ctx.division_cols = []
        return True
    if t == "Eastern Qualifying Standards":
        ctx.effective_year = 2027
        ctx.level = "Regionals"
        ctx.region = "Eastern"
        ctx.equipment = "Classic"
        ctx.event = None
        ctx.sex = None
        ctx.division_cols = []
        return True

    # 2027 event subtitles.
    if t == "Classic Powerlifting (3-Lift)":
        ctx.event = "SBD"
        ctx.sex = None
        ctx.division_cols = []
        return True
    if t == "Classic Bench Only":
        ctx.event = "B"
        ctx.sex = None
        ctx.division_cols = []
        return True

    # Equipped variants (parsed for completeness; filtered by orchestrator).
    if t in ("Equipped Powerlifting (3-Lift)",):
        ctx.event = "SBD"
        ctx.equipment = "Equipped"
        ctx.sex = None
        ctx.division_cols = []
        return True
    if t in ("Equipped Bench Only",):
        ctx.event = "B"
        ctx.equipment = "Equipped"
        ctx.sex = None
        ctx.division_cols = []
        return True

    return False


def _apply_header(ctx: _Context, row: list) -> bool:
    """
    Detect a column header row and update ctx.division_cols + sex.
    Returns True if row was a header.

    Two header styles:
      * 2026: ``['', 'Open', 'Sub-Junior', 'Junior', 'Master 1', ...]``
              (sex on the following row: ``['Men', '', '', ...]``)
      * 2027: ``['Women', 'Open', 'Sub-Junior', 'Junior', ...]``
    """
    if len(row) != 8:
        return False
    tail = [c.strip() if isinstance(c, str) else c for c in row[1:]]
    if any(c not in _DIVISION_HEADERS for c in tail):
        return False
    # Tail is a valid division header.
    ctx.division_cols = list(tail)
    first = (row[0] or "").strip()
    if first == "Men":
        ctx.sex = "M"
    elif first == "Women":
        ctx.sex = "F"
    # else: 2026 style, sex comes on the next row
    return True


def _apply_sex_marker(ctx: _Context, row: list) -> bool:
    """Detect a 2026-style standalone sex marker row."""
    first = (row[0] or "").strip() if row[0] is not None else ""
    if first not in ("Men", "Women"):
        return False
    if not _all_blank(row[1:]):
        return False
    ctx.sex = "M" if first == "Men" else "F"
    return True


def _parse_qt(token) -> float | None:
    """Parse a QT cell. ``-`` or blank means no QT at this cell."""
    if token is None:
        return None
    s = str(token).strip()
    if s in ("", "-", "—", "–"):
        return None
    try:
        return float(s)
    except ValueError as e:
        raise ValueError(f"cannot parse QT cell {token!r}") from e


def parse_pdf(pdf_path: Path) -> list[dict]:
    """
    Parse a CPU qualifying-total PDF into a list of row dicts.

    Each row dict has keys: ``sex, level, region, division, equipment,
    event, weight_class, qt, effective_year``. The orchestrator adds
    ``source_pdf`` and ``fetched_at`` before writing CSV.

    Raises ValueError on any structural surprise so bad PDFs fail loudly
    rather than silently emitting corrupt rows.
    """
    rows_out: list[dict] = []
    ctx = _Context()

    with pdfplumber.open(pdf_path) as pdf:
        all_table_rows: list[list] = []
        for page in pdf.pages:
            for tbl in page.extract_tables() or []:
                all_table_rows.extend(tbl)

    for raw in all_table_rows:
        row = list(raw) + [None] * (8 - len(raw)) if len(raw) < 8 else list(raw)[:8]

        # Skip fully-blank separator rows.
        if _all_blank(row):
            continue

        c0 = row[0]
        c0s = c0.strip() if isinstance(c0, str) else c0

        # Column-header row: tail matches division names. Check this
        # first so a 2027-style combo header (sex in c0, divisions in
        # c1..c7) isn't misread as a sex marker.
        if _apply_header(ctx, row):
            continue

        # Standalone sex marker (2026 style): c0 in {"Men", "Women"},
        # c1..c7 all blank. Must run before the title check because
        # sex markers look shape-identical to titles.
        if _apply_sex_marker(ctx, row):
            continue

        # Title / subtitle rows: c0 has text, c1..c7 all blank.
        if c0s and _all_blank(row[1:]):
            if _apply_title(ctx, c0s):
                continue
            log.warning("unknown title %r in %s", c0s, pdf_path.name)
            continue

        # Data row: c0 is a weight class, c1..c7 are QT values.
        if isinstance(c0s, str) and _WEIGHT_CLASS_RE.match(c0s):
            if not ctx.ready_for_data():
                raise ValueError(
                    f"data row before context ready in {pdf_path.name}: "
                    f"row={row} ctx={ctx}"
                )
            for div, val in zip(ctx.division_cols, row[1:8]):
                qt = _parse_qt(val)
                if qt is None:
                    continue
                rows_out.append({
                    "sex": ctx.sex,
                    "level": ctx.level,
                    "region": ctx.region,
                    "province": None,  # federal CPU rows are never provincial
                    "division": div,
                    "equipment": ctx.equipment,
                    "event": ctx.event,
                    "weight_class": c0s,
                    "qt": qt,
                    "effective_year": ctx.effective_year,
                })
            continue

        log.warning("unhandled row in %s: %r", pdf_path.name, row)

    log.info("parsed %d rows from %s", len(rows_out), pdf_path.name)
    return rows_out


def parse_pdfs(paths: Iterable[Path]) -> list[dict]:
    """Parse multiple PDFs and concatenate rows. Input order preserved."""
    out: list[dict] = []
    for p in paths:
        out.extend(parse_pdf(p))
    return out


# Regex to find anchor tags linking to a Wix-hosted PDF on the CPU site.
# Keeps the match narrow enough that stray .pdf links on other hosts
# (e.g. paralympic.org references in the page) are skipped.
_ANCHOR_PDF_RE = re.compile(
    r'<a[^>]*href="(https?://(?:www\.)?powerlifting\.ca/_files/ugd/[^"]+\.pdf)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(s: str) -> str:
    return _WHITESPACE_RE.sub(" ", _TAG_STRIP_RE.sub("", s)).strip()


def _http_get_text(url: str) -> str:
    """HTTP GET with retry + polite headers. Returns decoded body."""
    last_exc: Exception | None = None
    for attempt in range(1, _HTTP_RETRIES + 1):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_HTTP_TIMEOUT,
            )
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last_exc = e
            log.warning("GET %s attempt %d failed: %s", url, attempt, e)
            if attempt < _HTTP_RETRIES:
                time.sleep(_HTTP_BACKOFF_S * attempt)
    assert last_exc is not None  # for type checker
    raise last_exc


def _is_in_scope(label: str) -> bool:
    """
    Project-scope filter applied to CPU PDF link text.

    In scope: SBD Classic / Unequipped qualifying standards, either 2026
    (single PDF bundles Nationals + Regionals) or 2027 (separate PDFs
    per level + region). Out of scope: Equipped, 2026 bench-only, and
    any policy / procedure documents.

    Note: 2027 Classic PDFs contain both SBD and Bench Only tables in
    the same document. We download the whole PDF and filter Bench Only
    rows at the orchestrator level (see ``data/scrape_qt.filter_in_scope``).
    """
    low = label.lower()
    if "polic" in low or "procedure" in low:
        return False
    # 2026 standalone bench-only PDFs. 2027 bundle says "benchpress
    # only" inside a Classic PDF label, so we only reject the "bench
    # only" suffix (Classic label also contains "benchpress only", but
    # paired with "classic" which we accept below).
    if "bench only" in low and "classic" not in low:
        return False
    # Accept Unequipped (2026) or Classic (2027). Reject Equipped
    # variants (word-boundary match so "unequipped" doesn't trip it).
    if "unequipped" in low:
        return True
    if re.search(r"\bclassic\b", low):
        return True
    return False


def _extract_anchor_pdfs(html: str) -> list[tuple[str, str]]:
    """Return [(href, link_text)] for every Wix PDF anchor in ``html``."""
    out: list[tuple[str, str]] = []
    for m in _ANCHOR_PDF_RE.finditer(html):
        href = m.group(1)
        label = _strip_html(m.group(2))
        if not label:
            continue
        out.append((href, label))
    return out


def discover_pdf_urls(landing_urls: Iterable[str] = CPU_LANDING_URLS) -> list[dict]:
    """
    Fetch CPU landing pages and return in-scope PDF descriptors.

    Returned list has dicts: ``{"url": str, "label": str, "landing": str}``.
    URLs are deduped across landing pages (first occurrence wins).
    """
    out: list[dict] = []
    seen: set[str] = set()
    for page_url in landing_urls:
        log.info("fetching landing page %s", page_url)
        html = _http_get_text(page_url)
        for href, label in _extract_anchor_pdfs(html):
            if href in seen:
                continue
            if not _is_in_scope(label):
                log.debug("out of scope: %s (%s)", label, href)
                continue
            log.info("in scope: %s -> %s", label, href)
            seen.add(href)
            out.append({"url": href, "label": label, "landing": page_url})
    log.info("discover_pdf_urls: %d in-scope PDFs", len(out))
    return out


def download_pdf(url: str, target_dir: Path) -> Path:
    """
    Download ``url`` to ``target_dir`` and return the local path.

    Filename is derived from the Wix hash portion of the URL so each
    run produces stable, human-inspectable filenames when debugging.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    # URL shape: .../ugd/<group>_<hash>.pdf -> use hash as filename.
    stem = url.rsplit("/", 1)[-1]
    out = target_dir / stem
    last_exc: Exception | None = None
    for attempt in range(1, _HTTP_RETRIES + 1):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_HTTP_TIMEOUT,
                stream=True,
            )
            r.raise_for_status()
            with out.open("wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
            log.info("downloaded %s (%d bytes)", stem, out.stat().st_size)
            return out
        except requests.RequestException as e:
            last_exc = e
            log.warning("download %s attempt %d failed: %s", url, attempt, e)
            if attempt < _HTTP_RETRIES:
                time.sleep(_HTTP_BACKOFF_S * attempt)
    assert last_exc is not None
    raise last_exc
