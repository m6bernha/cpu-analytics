"""Tests for the sitemap generator.

The load-bearing property is the URL encoding. A sitemap URL must be
byte-for-byte what ``athletePath()`` / ``meetPath()`` in
``frontend/src/lib/route.ts`` produce, because the slug is the URL-encoded
EXACT OpenIPF name and the round trip has to be lossless.

A mismatch fails SILENTLY in the worst way: ``vercel.json`` rewrites every
``/athlete/*`` path to index.html, so a wrongly encoded URL still returns
200 and still renders the app shell. It just says "lifter not found". So
nothing short of these assertions catches it -- not the build, not a smoke
test that only checks status codes.

Expected values below were confirmed against the live site: each of the
accented / '#' / hyphenated cases was fetched from
https://cpu-analytics.vercel.app and returned the correct athlete in the
<title>, so these strings are observed behaviour, not a reimplementation of
what encodeURIComponent is assumed to do.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the ``data`` package importable from inside backend/tests/.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from data.generate_sitemap import (  # noqa: E402
    MAX_URLS_PER_FILE,
    encode_segment,
    _sitemap_index,
    _url_entry,
    _urlset,
)


# (raw name, expected encoding). encodeURIComponent leaves A-Za-z0-9-_.!~*'()
# alone and percent-encodes everything else in UTF-8.
ENCODING_CASES = [
    ("Enno Heisler", "Enno%20Heisler"),
    # Accents: two bytes each, verified live.
    ("Frédérick Day", "Fr%C3%A9d%C3%A9rick%20Day"),
    ("Amélie Picher-Plante", "Am%C3%A9lie%20Picher-Plante"),
    # OpenIPF disambiguates duplicate names with a trailing #N. '#' must
    # encode or the browser reads it as a fragment and the name truncates.
    ("Anthony Wong #2", "Anthony%20Wong%20%232"),
    # Unreserved set: none of these may be escaped.
    ("a-b_c.d~e", "a-b_c.d~e"),
    ("!*'()", "!*'()"),
    # Reserved characters that would otherwise change the URL's structure.
    ("a/b", "a%2Fb"),
    ("a?b", "a%3Fb"),
    ("a&b", "a%26b"),
    ("a+b", "a%2Bb"),
    ("a%b", "a%25b"),
    ("a#b", "a%23b"),
]


@pytest.mark.parametrize("raw,expected", ENCODING_CASES)
def test_encode_segment_matches_encode_uri_component(raw: str, expected: str) -> None:
    assert encode_segment(raw) == expected


def test_encode_segment_never_emits_url_structural_characters() -> None:
    """No encoded segment may contain a character that re-splits the path."""
    for raw, _ in ENCODING_CASES:
        encoded = encode_segment(raw)
        for char in "/?#&":
            assert char not in encoded, f"{raw!r} -> {encoded!r} leaked {char!r}"


def test_urlset_is_wellformed_and_escapes_xml() -> None:
    import xml.etree.ElementTree as ET

    # '&' survives as %26 from encoding, but assert the XML layer is safe
    # even if a raw ampersand ever reaches it.
    xml = _urlset([_url_entry("https://example.com/a&b", "2026-01-02")])
    root = ET.fromstring(xml)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert root.tag == f"{ns}urlset"
    assert root.find(f"{ns}url/{ns}loc").text == "https://example.com/a&b"
    assert root.find(f"{ns}url/{ns}lastmod").text == "2026-01-02"


def test_url_entry_omits_lastmod_when_unknown() -> None:
    assert "lastmod" not in _url_entry("https://example.com/")


def test_sitemap_index_is_wellformed() -> None:
    import xml.etree.ElementTree as ET

    xml = _sitemap_index([("sitemap-core.xml", None), ("sitemap-athletes.xml", "2026-07-24")])
    root = ET.fromstring(xml)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert root.tag == f"{ns}sitemapindex"
    locs = [e.text for e in root.findall(f"{ns}sitemap/{ns}loc")]
    assert all(loc.startswith("http") and loc.endswith(".xml") for loc in locs)
    assert len(locs) == 2


def test_chunk_cap_respects_the_sitemap_protocol_limit() -> None:
    """The spec caps a file at 50,000 URLs; we must stay under it."""
    assert MAX_URLS_PER_FILE <= 50_000
