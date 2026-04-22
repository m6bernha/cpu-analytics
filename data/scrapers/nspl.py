"""
Nova Scotia Powerlifting League provincial qualifying-total scraper.

NSPL publishes qualifying totals as a Google Sheet with four tabs:
``YYYY Provincial QTs`` and ``YYYY Regional QTs`` for each in-force
year. The Regional tabs duplicate CPU Regional Eastern data; we only
scrape the Provincial tabs because the federal CPU scraper already
covers Regional coverage.

Sheet layout (both years use the same shape):

  Row 0: Male Weight Class, Open, Sub-Junior, Junior, Master 1-4
  Rows 1-8: men 53, 59, 66, 74, 83, 93, 105, 120
  Row 9:   blank weight class cell -> 120+ (SHW men)
  Rows 10-17: women 43, 47, 52, 57, 63, 69, 76, 84
  Row 18: blank weight class cell -> 84+ (SHW women)

A "0" in a column means "no QT exists at this division"; those rows
are not emitted. NSPL's published numbers round up to the nearest
2.5 kg after multiplying 0.9 by the CPU Regional total, so derivation
from CPU is NOT a substitute for this scraper (~11 rows diverge by
+1.25 kg per year).

The Google Sheet ID is stable across revisions; NSPL adds new year
tabs rather than replacing the sheet. The scraper probes a range of
effective years and keeps whichever tabs return non-empty data.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

NSPL_LANDING_URL = (
    "https://sites.google.com/view/novascotiapowerlifting/"
    "getting-started/qualifying-requirements"
)
NSPL_SHEET_ID = "16uX-NiqUiwO_cR75e09-hpj--owzUvEi1WAAmXUgdnw"
_GVIZ_URL = (
    "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
    "?tqx=out:csv&sheet={sheet_name}"
)
_USER_AGENT = "cpu-analytics-scraper/1.0 (+contact matthias.bernhard7@gmail.com)"
_HTTP_TIMEOUT = 30.0

# Division columns in the sheet (positions 1-7 after the weight-class cell).
_DIVISION_COLUMNS = (
    "Open", "Sub-Junior", "Junior",
    "Master 1", "Master 2", "Master 3", "Master 4",
)

# Canonical weight-class sequences. The sheet leaves the cell blank for
# the SHW class; the parser uses these lists to fill it in.
_WC_M = ("53", "59", "66", "74", "83", "93", "105", "120", "120+")
_WC_F = ("43", "47", "52", "57", "63", "69", "76", "84", "84+")


def _gviz_csv_url(sheet_name: str, sheet_id: str = NSPL_SHEET_ID) -> str:
    return _GVIZ_URL.format(
        sheet_id=sheet_id,
        sheet_name=sheet_name.replace(" ", "%20"),
    )


def fetch_sheet_csv(sheet_name: str, sheet_id: str = NSPL_SHEET_ID) -> str:
    """Fetch one gviz CSV export. Raises HTTPError on 4xx/5xx."""
    url = _gviz_csv_url(sheet_name, sheet_id)
    r = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=_HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.text


def download_sheets(
    target_dir: Path,
    years: tuple[int, ...] = (2026, 2027),
    sheet_id: str = NSPL_SHEET_ID,
) -> list[tuple[int, Path]]:
    """Download Provincial QT tabs for each year into ``target_dir``.

    Returns ``[(year, local_csv_path), ...]`` for each year where the
    tab exists and has content. Missing tabs are logged and skipped.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    out: list[tuple[int, Path]] = []
    for y in years:
        sheet_name = f"{y} Provincial QTs"
        try:
            text = fetch_sheet_csv(sheet_name, sheet_id=sheet_id)
        except requests.HTTPError as e:
            log.warning("nspl: tab %r not found (%s)", sheet_name, e)
            continue
        if not text.strip():
            log.warning("nspl: tab %r returned empty body", sheet_name)
            continue
        dst = target_dir / f"nspl_{y}_provincial.csv"
        dst.write_text(text, encoding="utf-8")
        out.append((y, dst))
        log.info("downloaded nspl %s (%d bytes)", sheet_name, len(text))
    return out


def _parse_qt(cell: str) -> float | None:
    """Parse a QT cell. Blank and ``0``/``0.0`` map to "no QT"."""
    s = (cell or "").strip()
    if s in ("", "-"):
        return None
    try:
        val = float(s)
    except ValueError:
        return None
    if val == 0:
        return None
    return val


def parse_csv(csv_path: Path, effective_year: int) -> list[dict]:
    """Parse one Provincial-QT CSV tab.

    The sheet lists Men then Women; the parser expects exactly 9 data
    rows per sex. Raises RuntimeError if the row count drifts so a
    layout change fails loudly instead of silently emitting garbage.
    """
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = [r for r in reader if any(cell.strip() for cell in r)]

    if not rows:
        raise RuntimeError(f"empty csv {csv_path}")
    # Header sanity check -- protects against Regional tab being fed in.
    header0 = rows[0][0].strip().lower() if rows[0] else ""
    if "weight class" not in header0:
        raise RuntimeError(
            f"unexpected header in {csv_path}: {rows[0]!r}"
        )
    data = rows[1:]
    if len(data) != len(_WC_M) + len(_WC_F):
        raise RuntimeError(
            f"expected {len(_WC_M) + len(_WC_F)} data rows, got "
            f"{len(data)} in {csv_path}"
        )

    out: list[dict] = []
    sequences = (("M", _WC_M), ("F", _WC_F))
    cursor = 0
    for sex, wc_seq in sequences:
        for idx, wc in enumerate(wc_seq):
            row = data[cursor + idx]
            for col_idx, division in enumerate(_DIVISION_COLUMNS, start=1):
                cell = row[col_idx] if col_idx < len(row) else ""
                qt = _parse_qt(cell)
                if qt is None:
                    continue
                out.append({
                    "sex": sex,
                    "level": "Provincials",
                    "region": None,
                    "division": division,
                    "equipment": "Classic",
                    "event": "SBD",
                    "weight_class": wc,
                    "qt": qt,
                    "effective_year": effective_year,
                    "province": "Nova Scotia",
                })
        cursor += len(wc_seq)

    log.info(
        "parsed %d nspl rows for effective_year=%d", len(out), effective_year,
    )
    return out


def scrape_all(
    target_dir: Path,
    years: tuple[int, ...] = (2026, 2027),
) -> list[dict]:
    """Fetch + parse every available Provincial QT tab in ``years``.

    Returns a flat list of row dicts ready for the orchestrator to
    decorate with source URL and fetched_at.
    """
    results = download_sheets(target_dir, years=years)
    rows: list[dict] = []
    for y, path in results:
        rows.extend(parse_csv(path, effective_year=y))
    return rows


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# Convenience for ad-hoc CLI use during fixture regeneration.
def _debug_print_spot_checks(rows: list[dict]) -> None:
    by_key = {
        (r["effective_year"], r["sex"], r["division"], r["weight_class"]): r["qt"]
        for r in rows
    }
    for label, key in [
        ("2026 M 83 Open", (2026, "M", "Open", "83")),
        ("2026 F 63 Open", (2026, "F", "Open", "63")),
    ]:
        value = by_key.get(key, "MISSING")
        log.info("nspl spot-check %s = %s (scraped %s)", label, value, _today_iso())


# Backwards-compatible aliases so existing code paths can refer to
# ``fetch_sheet`` without knowing whether it returns text or a Path.
fetch_sheet = fetch_sheet_csv
