"""
Orchestrator for the live QT data pipeline.

High-level flow:

    1. Discover current PDF URLs on powerlifting.ca landing pages.
       (URLs rotate whenever CPU revises a standard.)
    2. Download each in-scope PDF to a temp directory.
    3. Parse each via ``data.scrapers.cpu.parse_pdf``.
    4. Filter to the project scope (Classic + SBD only; Equipped and
       Bench Only are out of scope per decision on 2026-04-21).
    5. Decorate with ``source_pdf`` and ``fetched_at``, sort, validate.
    6. Write ``qt_current.csv`` to ``--output-dir`` and diff against
       the ``--existing`` CSV if one was passed in.
    7. Emit GitHub-Actions outputs so the enclosing workflow knows
       whether to upload, commit a history snapshot, and open an issue.

The Python script is intentionally thin on GitHub-side actions. Upload
to the ``data-latest`` release, the snapshot commit, and the diff-summary
issue are all performed by ``.github/workflows/qt_refresh.yml`` using
the ``gh`` CLI. Separation of concerns: this script parses + validates
+ diffs; the workflow handles all side effects.

CLI:
    python -m data.scrape_qt --once --output-dir ./out [--existing ./old.csv]
    python -m data.scrape_qt --dry-run --output-dir ./out
    python -m data.scrape_qt --regenerate-fixtures
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from data.scrapers import base
from data.scrapers.cpu import discover_pdf_urls, download_pdf, parse_pdf
from data.scrapers import opa as opa_scraper
from data.scrapers import mpa as mpa_scraper

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "qt_pdfs"
QT_HISTORY_DIR = REPO_ROOT / "data" / "qt_history"

# Primary-key tuple used for deduping, sorting, and diffing. Every row
# must be unique on this tuple.
_KEY_FIELDS = (
    "effective_year", "sex", "level", "region", "province",
    "division", "equipment", "event", "weight_class",
)


def _row_key(r: dict) -> tuple:
    # None sorts before strings in Python; coerce to empty string so
    # Nationals rows (region=None) and Regionals rows sort predictably.
    return tuple(("" if r.get(k) is None else r[k]) for k in _KEY_FIELDS)


def filter_in_scope(rows: list[dict]) -> list[dict]:
    """Classic + SBD only. Equipped / Bench Only are dropped."""
    return [
        r for r in rows
        if r["equipment"] == "Classic" and r["event"] == "SBD"
    ]


def sort_rows(rows: list[dict]) -> list[dict]:
    """Deterministic row order for stable diffs across runs."""
    return sorted(rows, key=_row_key)


def diff_rows(old: list[dict], new: list[dict]) -> dict:
    """
    Structural diff between two row sets keyed on ``_KEY_FIELDS``.

    Returns ``{"added": [...], "removed": [...], "changed": [(old, new)]}``.
    "Changed" means the primary key matched but ``qt`` differs. Metadata
    fields (``source_pdf``, ``fetched_at``) are ignored for the diff so
    a re-fetch with identical QT values registers as no-change.
    """
    old_map = {_row_key(r): r for r in old}
    new_map = {_row_key(r): r for r in new}
    added_keys = new_map.keys() - old_map.keys()
    removed_keys = old_map.keys() - new_map.keys()
    shared_keys = old_map.keys() & new_map.keys()

    added = [new_map[k] for k in sorted(added_keys)]
    removed = [old_map[k] for k in sorted(removed_keys)]
    changed: list[tuple[dict, dict]] = []
    for k in sorted(shared_keys):
        if float(old_map[k]["qt"]) != float(new_map[k]["qt"]):
            changed.append((old_map[k], new_map[k]))
    return {"added": added, "removed": removed, "changed": changed}


def format_diff_summary(d: dict, *, title_date: str) -> str:
    """Render a diff dict as Markdown for a GitHub issue body."""
    lines = [
        f"# CPU QT standards changed on {title_date}",
        "",
        f"- Added: {len(d['added'])} rows",
        f"- Removed: {len(d['removed'])} rows",
        f"- Changed: {len(d['changed'])} rows",
        "",
        "This issue was opened automatically by the weekly `qt_refresh`",
        "GitHub Actions workflow. The new CSV has already been uploaded",
        "to the `data-latest` release; the backend will pick it up on",
        "its next cold start. Review the diff below and confirm the",
        "values match what CPU actually published before treating this",
        "as the new source of truth.",
        "",
    ]

    def fmt(r: dict) -> str:
        region = r.get("region") or "-"
        return (
            f"- {r['effective_year']} {r['sex']} {r['level']} "
            f"region={region} {r['equipment']} {r['event']} "
            f"{r['division']} @ {r['weight_class']} kg -> "
            f"**{r['qt']}** kg"
        )

    if d["added"]:
        lines.append("## Added")
        lines.extend(fmt(r) for r in d["added"])
        lines.append("")
    if d["removed"]:
        lines.append("## Removed")
        lines.extend(fmt(r) for r in d["removed"])
        lines.append("")
    if d["changed"]:
        lines.append("## Changed (QT value)")
        for old, new in d["changed"]:
            region = new.get("region") or "-"
            lines.append(
                f"- {new['effective_year']} {new['sex']} {new['level']} "
                f"region={region} {new['equipment']} {new['event']} "
                f"{new['division']} @ {new['weight_class']} kg: "
                f"{old['qt']} -> **{new['qt']}**"
            )
        lines.append("")

    return "\n".join(lines)


def _write_github_outputs(values: dict[str, str]) -> None:
    """
    Write to ``$GITHUB_OUTPUT`` so the enclosing GHA step sees the
    results. No-op locally (the env var only exists inside Actions).
    """
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        log.info("GITHUB_OUTPUT not set; skipping output emission "
                 "(values=%s)", values)
        return
    with open(out_path, "a", encoding="utf-8") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")


def _scrape_to_rows(tmpdir: Path) -> list[dict]:
    """Discover, download, parse (CPU federal + OPA provincial),
    decorate, scope-filter, sort."""
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_rows: list[dict] = []

    # CPU federal scrape (Nationals + Regionals).
    sources = discover_pdf_urls()
    if not sources:
        raise RuntimeError("no in-scope PDFs discovered on CPU landing pages")
    for s in sources:
        pdf_path = download_pdf(s["url"], tmpdir)
        rows = parse_pdf(pdf_path)
        for r in rows:
            r["source_pdf"] = s["url"]
            r["fetched_at"] = fetched_at
        all_rows.extend(rows)

    # OPA provincial scrape (Ontario). Graceful degrade -- a scraper
    # failure here must not take the whole pipeline down, since the CPU
    # federal side already has a fresh CSV to publish.
    try:
        opa_url = opa_scraper.discover_xlsx_url()
        opa_path = opa_scraper.download_xlsx(opa_url, tmpdir)
        opa_rows = opa_scraper.parse_xlsx(opa_path)
        for r in opa_rows:
            r["source_pdf"] = opa_url
            r["fetched_at"] = fetched_at
        all_rows.extend(opa_rows)
        log.info("OPA: %d provincial rows", len(opa_rows))
    except Exception as e:
        log.warning(
            "OPA scrape failed (%s); continuing without Ontario", e,
        )

    # MPA provincial scrape (Manitoba). Same graceful-degrade contract.
    try:
        mpa_url, _mpa_year = mpa_scraper.discover_pdf_url()
        mpa_path = mpa_scraper.download_pdf(mpa_url, tmpdir)
        mpa_rows = mpa_scraper.parse_pdf(mpa_path)
        for r in mpa_rows:
            r["source_pdf"] = mpa_url
            r["fetched_at"] = fetched_at
        all_rows.extend(mpa_rows)
        log.info("MPA: %d provincial rows", len(mpa_rows))
    except Exception as e:
        log.warning(
            "MPA scrape failed (%s); continuing without Manitoba", e,
        )

    log.info("parsed %d raw rows; applying scope filter", len(all_rows))
    scoped = filter_in_scope(all_rows)
    log.info("%d rows in scope (Classic + SBD)", len(scoped))
    scoped = sort_rows(scoped)
    base.validate_batch(scoped)
    return scoped


def run_once(
    *,
    output_dir: Path,
    existing_csv: Path | None,
    dry_run: bool,
    history_dir: Path = QT_HISTORY_DIR,
) -> int:
    """
    Scrape → validate → diff. Write candidate CSV + diff summary to
    ``output_dir`` and emit GHA outputs.

    Returns 0 on success (including "no change detected" and happy-path
    diff). Non-zero only on hard failures (network, parse, validation).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(prefix="qt_scrape_") as td:
        tmpdir = Path(td)
        rows = _scrape_to_rows(tmpdir)

    candidate_csv = output_dir / "qt_current.csv"
    n = base.write_csv(rows, candidate_csv)
    log.info("wrote candidate CSV: %s (%d rows)", candidate_csv, n)

    if existing_csv and existing_csv.exists():
        log.info("diffing against existing %s", existing_csv)
        old_rows = base.read_csv(existing_csv)
        d = diff_rows(old_rows, rows)
        changed = bool(d["added"] or d["removed"] or d["changed"])
    else:
        log.info("no existing CSV provided; treating as first publish")
        d = {"added": rows, "removed": [], "changed": []}
        changed = True

    today = datetime.now(timezone.utc).date().isoformat()
    summary_md = format_diff_summary(d, title_date=today)
    summary_path = output_dir / "qt_diff_summary.md"
    summary_path.write_text(summary_md, encoding="utf-8")

    snapshot_path = history_dir / f"{today}.csv"
    if changed and not dry_run:
        history_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            candidate_csv.read_text(encoding="utf-8"), encoding="utf-8",
        )
        log.info("wrote snapshot: %s", snapshot_path)

    _write_github_outputs({
        "changed": "true" if changed else "false",
        "csv_path": str(candidate_csv),
        "summary_path": str(summary_path),
        "snapshot_path": str(snapshot_path) if changed else "",
        "row_count": str(len(rows)),
        "added_count": str(len(d["added"])),
        "removed_count": str(len(d["removed"])),
        "changed_count": str(len(d["changed"])),
    })

    log.info(
        "done: changed=%s, added=%d, removed=%d, changed_qt=%d",
        changed, len(d["added"]), len(d["removed"]), len(d["changed"]),
    )
    return 0


def _parser_for_fixture(pdf_path: Path):
    """Dispatch the correct parser based on fixture filename prefix.

    * ``mpa_*.pdf`` -> Manitoba parser
    * anything else (``2026_*``, ``2027_*``) -> CPU federal parser
    """
    if pdf_path.stem.startswith("mpa_"):
        return mpa_scraper.parse_pdf
    return parse_pdf


def regenerate_fixtures() -> int:
    """
    Re-run the parser on every committed fixture PDF and rewrite its
    ``.expected.csv``. Only run this after an intentional parser change;
    otherwise the fixture drifts silently.
    """
    fields = tuple(
        k for k in base.CSV_FIELDS if k not in ("source_pdf", "fetched_at")
    )
    total = 0
    for pdf_path in sorted(FIXTURE_DIR.glob("*.pdf")):
        parser = _parser_for_fixture(pdf_path)
        rows = parser(pdf_path)
        for r in rows:
            base.validate_row(r)
        out = pdf_path.with_suffix(".expected.csv")
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(fields))
            w.writeheader()
            for r in rows:
                w.writerow({
                    k: ("" if r.get(k) is None else r.get(k)) for k in fields
                })
        log.info("regenerated %s (%d rows)", out.name, len(rows))
        total += len(rows)
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CPU QT scraper orchestrator")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true",
                      help="scrape + validate + diff; emit GHA outputs")
    mode.add_argument("--dry-run", action="store_true",
                      help="scrape + validate + diff; write candidate CSV "
                           "but skip snapshot commit")
    mode.add_argument("--regenerate-fixtures", action="store_true",
                      help="refresh committed .expected.csv fixtures")
    parser.add_argument("--output-dir", type=Path,
                        help="where to write qt_current.csv + diff summary")
    parser.add_argument("--existing", type=Path, default=None,
                        help="path to last-published CSV for diffing "
                             "(if omitted, treat as first publish)")
    parser.add_argument("--log-level", default="INFO",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )

    if args.regenerate_fixtures:
        regenerate_fixtures()
        return 0

    if args.output_dir is None:
        parser.error("--output-dir is required with --once or --dry-run")
    return run_once(
        output_dir=args.output_dir,
        existing_csv=args.existing,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
