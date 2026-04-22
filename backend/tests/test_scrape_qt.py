"""
Fixture-based tests for the CPU qualifying-total scraper.

Committed fixtures live in ``backend/tests/fixtures/qt_pdfs/``:
  * one ``.pdf`` per source document (snapshot from powerlifting.ca)
  * one matching ``.expected.csv`` locking in parser output

These tests re-run the parser against each committed PDF and assert the
output matches the expected CSV row-for-row. They guard against:
  * accidental regressions to the parser state machine
  * silent drift when we upgrade pdfplumber
  * CPU restructuring the PDF (test will fail loudly, someone investigates)

To update a fixture after an intentional parser change:
  cd cpu-analytics
  .venv/Scripts/python -m data.scrape_qt --regenerate-fixtures
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

# Make the ``data`` package importable from inside backend/tests/.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from data.scrapers import base  # noqa: E402
from data.scrapers.cpu import parse_pdf  # noqa: E402


FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "qt_pdfs"

# CPU federal PDFs all start with a year (2026_*, 2027_*). Provincial
# PDFs use a federation-prefix naming convention (mpa_*, etc.) so the
# CPU-specific parametrised tests don't see them.
PDF_FIXTURES = sorted(
    p for p in FIXTURE_DIR.glob("*.pdf") if p.stem[:4].isdigit()
)
MPA_PDF_FIXTURES = sorted(FIXTURE_DIR.glob("mpa_*.pdf"))

# Columns in the expected CSV (parser output schema).
EXPECTED_FIELDS = tuple(
    k for k in base.CSV_FIELDS if k not in ("source_pdf", "fetched_at")
)


def _load_expected(path: Path) -> list[dict]:
    """Read expected.csv back in the same dict shape the parser emits."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        out: list[dict] = []
        for r in reader:
            out.append({
                "sex": r["sex"],
                "level": r["level"],
                "region": r["region"] or None,
                "province": r.get("province") or None,
                "division": r["division"],
                "equipment": r["equipment"],
                "event": r["event"],
                "weight_class": r["weight_class"],
                "qt": float(r["qt"]),
                "effective_year": int(r["effective_year"]),
            })
    return out


@pytest.mark.parametrize("pdf_path", PDF_FIXTURES, ids=lambda p: p.stem)
def test_parse_pdf_matches_fixture(pdf_path: Path) -> None:
    expected_csv = pdf_path.with_suffix(".expected.csv")
    assert expected_csv.exists(), (
        f"missing expected fixture {expected_csv.name}; "
        "regenerate with python -m data.scrape_qt --regenerate-fixtures"
    )

    actual = parse_pdf(pdf_path)
    expected = _load_expected(expected_csv)

    assert len(actual) == len(expected), (
        f"row count drift: parser={len(actual)} fixture={len(expected)}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, f"row {i} differs:\n  got:      {a}\n  expected: {e}"


@pytest.mark.parametrize("pdf_path", PDF_FIXTURES, ids=lambda p: p.stem)
def test_parsed_rows_pass_row_validation(pdf_path: Path) -> None:
    for row in parse_pdf(pdf_path):
        base.validate_row(row)


def test_combined_batch_passes_batch_validation() -> None:
    """All 4 federal PDFs combined must form a valid batch."""
    rows: list[dict] = []
    for pdf in PDF_FIXTURES:
        rows.extend(parse_pdf(pdf))
    assert rows, "no rows parsed from fixture PDFs"
    base.validate_batch(rows)


def test_sbd_only_filter_is_nonempty() -> None:
    """Scope is SBD Classic. Combined SBD slice must cover both sexes,
    both levels, both regions, Open + Junior + at least one Master."""
    rows: list[dict] = []
    for pdf in PDF_FIXTURES:
        rows.extend(parse_pdf(pdf))
    sbd = [r for r in rows if r["event"] == "SBD" and r["equipment"] == "Classic"]
    assert len(sbd) > 0
    sexes = {r["sex"] for r in sbd}
    levels = {r["level"] for r in sbd}
    divisions = {r["division"] for r in sbd}
    regions = {r["region"] for r in sbd}
    assert sexes == {"M", "F"}
    assert levels == {"Nationals", "Regionals"}
    assert "Western/Central" in regions
    assert "Eastern" in regions
    assert "Open" in divisions
    assert "Junior" in divisions
    assert any(d.startswith("Master") for d in divisions)


def test_no_dash_rows_emitted() -> None:
    """A ``-`` or blank cell in the PDF must not produce a row."""
    rows: list[dict] = []
    for pdf in PDF_FIXTURES:
        rows.extend(parse_pdf(pdf))
    # Men 53kg Open is always "-" or blank across all 4 PDFs.
    m53_open = [
        r for r in rows
        if r["sex"] == "M" and r["weight_class"] == "53" and r["division"] == "Open"
    ]
    assert m53_open == [], f"expected no rows for Men 53 Open, got {m53_open}"


# -------------------------------------------------------------------------
# Orchestrator tests (filter_in_scope, diff_rows, sort_rows, run_once)
# -------------------------------------------------------------------------

from data import scrape_qt  # noqa: E402


def _fixture_rows() -> list[dict]:
    """Every row from every fixture PDF, with source metadata."""
    out: list[dict] = []
    for pdf in PDF_FIXTURES:
        for r in parse_pdf(pdf):
            r["source_pdf"] = pdf.name
            r["fetched_at"] = "2026-04-21T00:00:00+00:00"
            out.append(r)
    return out


def test_filter_in_scope_drops_bench_only_and_equipped() -> None:
    rows = _fixture_rows()
    bench_count = sum(1 for r in rows if r["event"] == "B")
    assert bench_count > 0, "fixture should contain Bench rows (2027 PDFs)"
    scoped = scrape_qt.filter_in_scope(rows)
    assert all(r["event"] == "SBD" for r in scoped)
    assert all(r["equipment"] == "Classic" for r in scoped)
    assert len(scoped) < len(rows), "scope filter must remove rows"


def test_sort_rows_is_stable_and_deterministic() -> None:
    rows = scrape_qt.filter_in_scope(_fixture_rows())
    once = scrape_qt.sort_rows(rows)
    twice = scrape_qt.sort_rows(list(reversed(rows)))
    assert once == twice, "sort order must be input-independent"


def test_diff_rows_no_change() -> None:
    rows = scrape_qt.sort_rows(scrape_qt.filter_in_scope(_fixture_rows()))
    d = scrape_qt.diff_rows(rows, rows)
    assert d == {"added": [], "removed": [], "changed": []}


def test_diff_rows_detects_qt_change() -> None:
    rows = scrape_qt.sort_rows(scrape_qt.filter_in_scope(_fixture_rows()))
    # Copy + mutate one row's QT.
    mutated = [dict(r) for r in rows]
    mutated[0]["qt"] = mutated[0]["qt"] + 2.5
    d = scrape_qt.diff_rows(rows, mutated)
    assert d["added"] == []
    assert d["removed"] == []
    assert len(d["changed"]) == 1
    old, new = d["changed"][0]
    assert new["qt"] - old["qt"] == 2.5


def test_diff_rows_detects_add_and_remove() -> None:
    rows = scrape_qt.sort_rows(scrape_qt.filter_in_scope(_fixture_rows()))
    fewer = rows[:-1]
    d = scrape_qt.diff_rows(fewer, rows)
    assert len(d["added"]) == 1
    assert d["removed"] == []
    d2 = scrape_qt.diff_rows(rows, fewer)
    assert d2["added"] == []
    assert len(d2["removed"]) == 1


def test_format_diff_summary_renders_key_sections() -> None:
    rows = scrape_qt.sort_rows(scrape_qt.filter_in_scope(_fixture_rows()))[:3]
    d = {
        "added": [rows[0]],
        "removed": [rows[1]],
        "changed": [(rows[2], {**rows[2], "qt": rows[2]["qt"] + 5}) ],
    }
    md = scrape_qt.format_diff_summary(d, title_date="2026-04-21")
    assert "## Added" in md
    assert "## Removed" in md
    assert "## Changed" in md
    assert "2026-04-21" in md


def test_run_once_first_publish_writes_csv_and_snapshot(
    tmp_path, monkeypatch,
) -> None:
    """End-to-end orchestrator run using fixture PDFs in place of network
    downloads. Verifies: CSV written, snapshot written on first publish,
    changed=True flagged."""
    # Stub discover_pdf_urls to return fixtures (bypass network) and
    # download_pdf to copy the fixture instead of fetching.
    fixture_sources = [
        {"url": f"fixture://{p.name}", "label": p.stem, "landing": "fixture"}
        for p in PDF_FIXTURES
    ]

    def fake_discover(_landing_urls=None):
        return fixture_sources

    def fake_download(url, target_dir):
        name = url.removeprefix("fixture://")
        src = FIXTURE_DIR / name
        dst = target_dir / name
        dst.write_bytes(src.read_bytes())
        return dst

    monkeypatch.setattr(scrape_qt, "discover_pdf_urls", fake_discover)
    monkeypatch.setattr(scrape_qt, "download_pdf", fake_download)

    out_dir = tmp_path / "out"
    history = tmp_path / "history"
    rc = scrape_qt.run_once(
        output_dir=out_dir,
        existing_csv=None,
        dry_run=False,
        history_dir=history,
    )
    assert rc == 0
    assert (out_dir / "qt_current.csv").exists()
    assert (out_dir / "qt_diff_summary.md").exists()
    # Snapshot written on first publish.
    snaps = list(history.glob("*.csv"))
    assert len(snaps) == 1, f"expected one snapshot, got {snaps}"


def test_run_once_no_change_skips_snapshot(tmp_path, monkeypatch) -> None:
    fixture_sources = [
        {"url": f"fixture://{p.name}", "label": p.stem, "landing": "fixture"}
        for p in PDF_FIXTURES
    ]
    monkeypatch.setattr(
        scrape_qt, "discover_pdf_urls",
        lambda _=None: fixture_sources,
    )
    monkeypatch.setattr(
        scrape_qt, "download_pdf",
        lambda url, target_dir: (
            target_dir / url.removeprefix("fixture://"),
            (target_dir / url.removeprefix("fixture://")).write_bytes(
                (FIXTURE_DIR / url.removeprefix("fixture://")).read_bytes()
            ),
        )[0],
    )
    out1 = tmp_path / "run1"
    history = tmp_path / "history"
    scrape_qt.run_once(
        output_dir=out1, existing_csv=None, dry_run=False,
        history_dir=history,
    )
    first_snap_count = len(list(history.glob("*.csv")))

    out2 = tmp_path / "run2"
    scrape_qt.run_once(
        output_dir=out2,
        existing_csv=out1 / "qt_current.csv",
        dry_run=False,
        history_dir=history,
    )
    second_snap_count = len(list(history.glob("*.csv")))
    # Identical scrape -> no new snapshot even though run succeeded.
    assert first_snap_count == second_snap_count


# -------------------------------------------------------------------------
# OPA provincial scraper tests (Excel from Dropbox)
# -------------------------------------------------------------------------

from data.scrapers import opa as opa_scraper  # noqa: E402

OPA_FIXTURE = FIXTURE_DIR / "opa_provincial_classic.xlsx"


def test_opa_parse_xlsx_expected_shape() -> None:
    rows = opa_scraper.parse_xlsx(OPA_FIXTURE)
    # OPA Classic: 7 divisions x 2 sexes, 9 weight classes each, minus
    # "-" entries. Observed total: 116 rows.
    assert 100 <= len(rows) <= 130, f"unexpected row count {len(rows)}"
    for r in rows:
        assert r["level"] == "Provincials"
        assert r["province"] == "Ontario"
        assert r["equipment"] == "Classic"
        assert r["event"] == "SBD"
        assert r["region"] is None


def test_opa_open_rows_match_known_values() -> None:
    """Spot-check well-known QTs from the OPA Classic Open 2026 table."""
    rows = opa_scraper.parse_xlsx(OPA_FIXTURE)
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"]
        for r in rows
    }
    # From the Excel: Men Open 83kg = 570.0, Women Open 63kg = 302.5.
    assert by_key[("M", "Open", "83")] == 570.0
    assert by_key[("F", "Open", "63")] == 302.5
    # Men 53kg Open is "-" (no QT); should not be emitted.
    assert ("M", "Open", "53") not in by_key


def test_opa_rows_pass_validation() -> None:
    for row in opa_scraper.parse_xlsx(OPA_FIXTURE):
        base.validate_row(row)


# -------------------------------------------------------------------------
# MPA provincial scraper tests (PDF from manitobapowerlifting.ca)
# -------------------------------------------------------------------------

from data.scrapers import mpa as mpa_scraper  # noqa: E402


def test_mpa_pdf_fixtures_present() -> None:
    """Regression guard: if someone deletes the MPA fixture by accident
    the tests below silently skip the real check; fail loudly here."""
    assert MPA_PDF_FIXTURES, "no mpa_*.pdf fixture found"


@pytest.mark.parametrize("pdf_path", MPA_PDF_FIXTURES, ids=lambda p: p.stem)
def test_mpa_parse_pdf_matches_expected_csv(pdf_path: Path) -> None:
    """Row-for-row lock against committed expected CSV."""
    expected_csv = pdf_path.with_suffix(".expected.csv")
    assert expected_csv.exists(), (
        f"missing {expected_csv.name}; "
        "regenerate with python -m data.scrape_qt --regenerate-fixtures"
    )
    actual = mpa_scraper.parse_pdf(pdf_path)
    expected = _load_expected(expected_csv)
    assert len(actual) == len(expected), (
        f"row count drift: parser={len(actual)} fixture={len(expected)}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, f"row {i} differs:\n  got:      {a}\n  expected: {e}"


@pytest.mark.parametrize("pdf_path", MPA_PDF_FIXTURES, ids=lambda p: p.stem)
def test_mpa_open_rows_match_audit_values(pdf_path: Path) -> None:
    """Audit spot-checks from 2026-04-22 provincial landscape report."""
    rows = mpa_scraper.parse_pdf(pdf_path)
    scope = [
        r for r in rows if r["equipment"] == "Classic" and r["event"] == "SBD"
    ]
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"] for r in scope
    }
    assert by_key[("M", "Open", "83")] == 517.5
    assert by_key[("F", "Open", "63")] == 290.0
    assert by_key[("M", "Master 1", "83")] == 420.0
    assert by_key[("F", "Sub-Junior", "63")] == 180.0


@pytest.mark.parametrize("pdf_path", MPA_PDF_FIXTURES, ids=lambda p: p.stem)
def test_mpa_rows_pass_row_validation(pdf_path: Path) -> None:
    for row in mpa_scraper.parse_pdf(pdf_path):
        base.validate_row(row)


def test_mpa_province_is_set_and_level_is_provincials() -> None:
    for pdf_path in MPA_PDF_FIXTURES:
        for r in mpa_scraper.parse_pdf(pdf_path):
            assert r["province"] == "Manitoba"
            assert r["level"] == "Provincials"
            assert r["region"] is None


# -------------------------------------------------------------------------
# NSPL provincial scraper tests (Google Sheet gviz CSV export)
# -------------------------------------------------------------------------

from data.scrapers import nspl as nspl_scraper  # noqa: E402


NSPL_FIXTURES = sorted(
    (FIXTURE_DIR / f"nspl_{y}_provincial.source.csv", y)
    for y in (2026, 2027)
    if (FIXTURE_DIR / f"nspl_{y}_provincial.source.csv").exists()
)


def test_nspl_source_fixtures_present() -> None:
    assert NSPL_FIXTURES, "no nspl_*.source.csv fixtures found"


@pytest.mark.parametrize(
    "src_csv,year",
    NSPL_FIXTURES,
    ids=lambda v: v if isinstance(v, int) else v.stem,
)
def test_nspl_parse_matches_expected_csv(src_csv: Path, year: int) -> None:
    expected_csv = (
        src_csv.parent / f"nspl_{year}_provincial.expected.csv"
    )
    assert expected_csv.exists(), (
        f"missing {expected_csv.name}; regenerate with the scraper CLI"
    )
    actual = nspl_scraper.parse_csv(src_csv, effective_year=year)
    expected = _load_expected(expected_csv)
    assert len(actual) == len(expected), (
        f"row count drift: parser={len(actual)} fixture={len(expected)}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, f"row {i} differs:\n  got:      {a}\n  expected: {e}"


@pytest.mark.parametrize("src_csv,year", NSPL_FIXTURES, ids=lambda v: v)
def test_nspl_open_rows_match_audit_values(src_csv: Path, year: int) -> None:
    rows = nspl_scraper.parse_csv(src_csv, effective_year=year)
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"] for r in rows
    }
    if year == 2026:
        assert by_key[("M", "Open", "83")] == 482.5
        assert by_key[("F", "Open", "63")] == 272.5


def test_nspl_drops_zero_cells() -> None:
    """Men 53 Open and Women 43 Open are encoded as 0 (no QT); the parser
    must not emit rows for them."""
    src, year = NSPL_FIXTURES[0]
    rows = nspl_scraper.parse_csv(src, effective_year=year)
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"] for r in rows
    }
    assert ("M", "Open", "53") not in by_key
    assert ("F", "Open", "43") not in by_key
    # Sub-Junior / Junior at those classes DO exist.
    assert ("M", "Sub-Junior", "53") in by_key
    assert ("F", "Sub-Junior", "43") in by_key


def test_nspl_values_deviate_from_simple_cpu_derivation() -> None:
    """Audit invariant: NSPL rounds up to 2.5 kg after 0.9 x CPU Regional,
    which makes derivation from CPU insufficient. Spot-check one known
    divergence: M 59 Open 2026 is 372.5 on the NSPL sheet, not 371.25
    (which is the raw 0.9 x 412.5)."""
    src, _ = NSPL_FIXTURES[0]
    rows = nspl_scraper.parse_csv(src, effective_year=2026)
    m59_open = next(
        r for r in rows
        if r["sex"] == "M" and r["division"] == "Open"
        and r["weight_class"] == "59"
    )
    assert m59_open["qt"] == 372.5


def test_nspl_rows_pass_validation() -> None:
    for src, year in NSPL_FIXTURES:
        for r in nspl_scraper.parse_csv(src, effective_year=year):
            base.validate_row(r)


def test_nspl_province_and_level_locked() -> None:
    for src, year in NSPL_FIXTURES:
        for r in nspl_scraper.parse_csv(src, effective_year=year):
            assert r["province"] == "Nova Scotia"
            assert r["level"] == "Provincials"
            assert r["region"] is None
            assert r["equipment"] == "Classic"
            assert r["event"] == "SBD"


# -------------------------------------------------------------------------
# NLPA provincial scraper tests (.docx via Google Docs export)
# -------------------------------------------------------------------------

from data.scrapers import nlpa as nlpa_scraper  # noqa: E402


NLPA_DOCX_FIXTURES = sorted(FIXTURE_DIR.glob("nlpa_*.docx"))


def test_nlpa_fixture_present() -> None:
    assert NLPA_DOCX_FIXTURES, "no nlpa_*.docx fixture found"


@pytest.mark.parametrize(
    "docx_path", NLPA_DOCX_FIXTURES, ids=lambda p: p.stem,
)
def test_nlpa_parse_matches_expected_csv(docx_path: Path) -> None:
    expected_csv = docx_path.with_suffix(".expected.csv")
    assert expected_csv.exists(), f"missing {expected_csv.name}"
    actual = nlpa_scraper.parse_docx(docx_path)
    expected = _load_expected(expected_csv)
    assert len(actual) == len(expected), (
        f"row count drift: parser={len(actual)} fixture={len(expected)}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, f"row {i} differs:\n  got:      {a}\n  expected: {e}"


@pytest.mark.parametrize(
    "docx_path", NLPA_DOCX_FIXTURES, ids=lambda p: p.stem,
)
def test_nlpa_classic_sbd_open_rows_match_audit_values(docx_path: Path) -> None:
    """Audit spot checks for Classic + SBD section only."""
    rows = nlpa_scraper.parse_docx(docx_path)
    scope = [
        r for r in rows if r["equipment"] == "Classic" and r["event"] == "SBD"
    ]
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"] for r in scope
    }
    assert by_key[("M", "Open", "83")] == 507.5
    assert by_key[("F", "Open", "63")] == 287.5
    assert by_key[("M", "Master 1", "83")] == 427.5
    assert by_key[("F", "Master 2", "63")] == 180.0


@pytest.mark.parametrize(
    "docx_path", NLPA_DOCX_FIXTURES, ids=lambda p: p.stem,
)
def test_nlpa_rows_pass_row_validation(docx_path: Path) -> None:
    for row in nlpa_scraper.parse_docx(docx_path):
        base.validate_row(row)


def test_nlpa_province_and_level_locked() -> None:
    for docx_path in NLPA_DOCX_FIXTURES:
        for r in nlpa_scraper.parse_docx(docx_path):
            assert r["province"] == "Newfoundland and Labrador"
            assert r["level"] == "Provincials"
            assert r["region"] is None


def test_nlpa_effective_year_from_creation_date() -> None:
    """The 2022 NLPA doc has no year in its title text; parser falls
    back to the file's creation year (2022)."""
    for docx_path in NLPA_DOCX_FIXTURES:
        rows = nlpa_scraper.parse_docx(docx_path)
        years = {r["effective_year"] for r in rows}
        assert years == {2022}, (
            f"expected all rows at effective_year=2022, got {years}"
        )


def test_nlpa_staleness_warning_is_logged(caplog) -> None:
    """The committed fixture is from 2022 so it MUST trigger the
    staleness warning. When NLPA refreshes the doc, the test will fail
    and the fixture needs re-committing."""
    import logging as _logging
    caplog.set_level(_logging.WARNING, logger="data.scrapers.nlpa")
    nlpa_scraper.parse_docx(NLPA_DOCX_FIXTURES[0])
    assert any("stale" in rec.message for rec in caplog.records), (
        f"no staleness warning emitted; records: {caplog.records}"
    )


# -------------------------------------------------------------------------
# APU provincial scraper tests (JPG images + hash-matched transcription)
# -------------------------------------------------------------------------

from data.scrapers import apu as apu_scraper  # noqa: E402


def test_apu_transcribed_directory_present() -> None:
    assert apu_scraper.TRANSCRIBED_DIR.exists(), (
        "data/scrapers/apu_transcribed missing"
    )
    releases = [
        d for d in apu_scraper.TRANSCRIBED_DIR.iterdir()
        if d.is_dir() and d.name.isdigit()
    ]
    assert releases, "no release subdirs under apu_transcribed"


def test_apu_latest_transcribed_rows_match_audit_values() -> None:
    rows = apu_scraper.load_latest_transcribed()
    assert rows, "load_latest_transcribed() returned no rows"
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"] for r in rows
    }
    assert by_key[("M", "Open", "83")] == 525.0
    assert by_key[("F", "Open", "63")] == 297.5
    assert by_key[("M", "Master 1", "83")] == 450.0
    assert by_key[("F", "Sub-Junior", "63")] == 185.0


def test_apu_rows_pass_row_validation() -> None:
    for row in apu_scraper.load_latest_transcribed():
        base.validate_row(row)


def test_apu_province_and_level_locked() -> None:
    rows = apu_scraper.load_latest_transcribed()
    assert rows, "expected non-empty APU rows"
    for r in rows:
        assert r["province"] == "Alberta"
        assert r["level"] == "Provincials"
        assert r["region"] is None
        assert r["equipment"] == "Classic"
        assert r["event"] == "SBD"


def test_apu_rows_include_expected_cardinality() -> None:
    """Men table has 58 non-blank cells (9 classes x 7 divisions minus
    the 4 blank Master cells at 53kg plus 1 blank Open at 53 kg = 58).
    Women table is the same shape. Total: 116 rows expected."""
    rows = apu_scraper.load_latest_transcribed()
    assert len(rows) == 116, f"expected 116 Classic SBD rows, got {len(rows)}"


def test_apu_source_hashes_line_up_with_live_sample_format() -> None:
    """Sanity check on the committed source_hashes.csv format so a later
    hand edit that drops a row fails loudly instead of silently skipping
    the hash check."""
    for release_dir in apu_scraper.TRANSCRIBED_DIR.iterdir():
        if not release_dir.is_dir() or not release_dir.name.isdigit():
            continue
        hashes = apu_scraper._load_source_hashes(release_dir)
        assert hashes, f"{release_dir} has empty source_hashes.csv"
        # Every hash must be a 64-char hex string.
        for name, h in hashes.items():
            assert len(h) == 64 and all(c in "0123456789abcdef" for c in h), (
                f"bad hash for {name} in {release_dir}: {h!r}"
            )


# -------------------------------------------------------------------------
# FQD provincial scraper tests (JSON API via Heroku backend)
# -------------------------------------------------------------------------

from data.scrapers import fqd as fqd_scraper  # noqa: E402


FQD_SNAPSHOT = FIXTURE_DIR / "fqd_standards.json"


def test_fqd_snapshot_fixture_present() -> None:
    assert FQD_SNAPSHOT.exists(), "missing fqd_standards.json fixture"


def test_fqd_parse_matches_expected_csv() -> None:
    expected_csv = FQD_SNAPSHOT.with_suffix(".expected.csv")
    assert expected_csv.exists(), f"missing {expected_csv.name}"
    actual = fqd_scraper.parse_json_file(FQD_SNAPSHOT)
    expected = _load_expected(expected_csv)
    assert len(actual) == len(expected), (
        f"row count drift: parser={len(actual)} fixture={len(expected)}"
    )
    for i, (a, e) in enumerate(zip(actual, expected)):
        assert a == e, f"row {i} differs:\n  got:      {a}\n  expected: {e}"


def test_fqd_classic_sbd_open_rows_match_audit_values() -> None:
    """Audit spot checks (Provincial Classic + SBD only)."""
    rows = fqd_scraper.parse_json_file(FQD_SNAPSHOT)
    scope = [
        r for r in rows if r["equipment"] == "Classic" and r["event"] == "SBD"
    ]
    by_key = {
        (r["sex"], r["division"], r["weight_class"]): r["qt"] for r in scope
    }
    assert by_key[("M", "Open", "83")] == 625.0
    assert by_key[("F", "Open", "63")] == 345.0
    assert by_key[("M", "Master 1", "83")] == 450.0
    assert by_key[("F", "Master 1", "63")] == 227.5


def test_fqd_drops_nationals_rows() -> None:
    """The FQD API returns both Nationals and Provincials; only
    Provincials rows should reach our output because CPU already owns
    Nationals globally."""
    import json
    raw = json.loads(FQD_SNAPSHOT.read_text(encoding="utf-8"))
    nats_count = sum(1 for d in raw if d.get("level") == "nats")
    assert nats_count > 0, (
        "fixture should contain nationals records to prove the filter"
    )
    rows = fqd_scraper.parse_json_file(FQD_SNAPSHOT)
    assert all(r["level"] == "Provincials" for r in rows)


def test_fqd_rows_pass_row_validation() -> None:
    for row in fqd_scraper.parse_json_file(FQD_SNAPSHOT):
        base.validate_row(row)


def test_fqd_province_locked() -> None:
    for r in fqd_scraper.parse_json_file(FQD_SNAPSHOT):
        assert r["province"] == "Quebec"
        assert r["level"] == "Provincials"
        assert r["region"] is None


def test_fqd_weight_class_normalisation() -> None:
    """The API returns '-83 kg' / '120+ kg' / '84+ kg'. The parser must
    normalise to '83' / '120+' / '84+' to match base.VALID_WEIGHT_CLASSES."""
    rows = fqd_scraper.parse_json_file(FQD_SNAPSHOT)
    wcs = {r["weight_class"] for r in rows if r["sex"] == "M"}
    assert "83" in wcs
    assert "120+" in wcs
    # Never leaves the raw API format in the output.
    assert not any(w.startswith("-") for w in wcs)
    assert not any(w.endswith(" kg") for w in wcs)


def test_run_once_emits_github_outputs(tmp_path, monkeypatch) -> None:
    fixture_sources = [
        {"url": f"fixture://{p.name}", "label": p.stem, "landing": "fixture"}
        for p in PDF_FIXTURES
    ]
    monkeypatch.setattr(scrape_qt, "discover_pdf_urls", lambda _=None: fixture_sources)

    def fake_download(url, target_dir):
        name = url.removeprefix("fixture://")
        dst = target_dir / name
        dst.write_bytes((FIXTURE_DIR / name).read_bytes())
        return dst
    monkeypatch.setattr(scrape_qt, "download_pdf", fake_download)

    outputs_file = tmp_path / "gh_out"
    outputs_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs_file))

    scrape_qt.run_once(
        output_dir=tmp_path / "out",
        existing_csv=None, dry_run=True,
        history_dir=tmp_path / "history",
    )
    content = outputs_file.read_text(encoding="utf-8")
    assert "changed=true" in content
    assert "row_count=" in content
    assert "added_count=" in content
