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
PDF_FIXTURES = sorted(FIXTURE_DIR.glob("*.pdf"))

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
