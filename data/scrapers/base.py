"""
Shared schema, validation, and CSV I/O for QT scrapers.

The live-scrape pipeline emits rows with this schema (one row per
sex x level x region x division x equipment x event x weight_class).
Historical pre-2025 values stay in the vendored
``data/qualifying_totals_canpl.csv``; this file defines only the
live-scrape format (2026+).
"""
from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger(__name__)

# Column order for qt_current.csv. Scrapers emit dicts using these keys
# (minus source_pdf / fetched_at, which the orchestrator adds).
CSV_FIELDS = (
    "sex",
    "level",
    "region",
    "province",
    "division",
    "equipment",
    "event",
    "weight_class",
    "qt",
    "effective_year",
    "source_pdf",
    "fetched_at",
)

# Enum-like allowed values. Used for validation and as the frontend's
# filter-panel source of truth.
VALID_SEX = ("M", "F")
VALID_LEVEL = ("Nationals", "Regionals", "Provincials")
VALID_REGION = (None, "Western/Central", "Eastern")
# Canadian provinces that have their own powerlifting federation.
# ``province`` is only populated when Level=Provincials. For federal
# (Nationals / Regionals) rows the field stays None.
VALID_PROVINCE = (
    None,
    "British Columbia", "Alberta", "Saskatchewan", "Manitoba",
    "Ontario", "Quebec",
    "New Brunswick", "Nova Scotia", "Prince Edward Island",
    "Newfoundland and Labrador",
)
VALID_DIVISION = (
    "Open", "Sub-Junior", "Junior",
    "Master 1", "Master 2", "Master 3", "Master 4",
)
VALID_EQUIPMENT = ("Classic", "Equipped")
VALID_EVENT = ("SBD", "B")
VALID_WEIGHT_CLASSES_M = ("53", "59", "66", "74", "83", "93", "105", "120", "120+")
VALID_WEIGHT_CLASSES_F = ("43", "47", "52", "57", "63", "69", "76", "84", "84+")

# QT sanity bounds. Bench-only values can go quite low; full-power can
# go quite high. Anything outside this range is a parser bug.
QT_MIN_KG = 20.0
QT_MAX_KG = 900.0

# Expected row count bounds for the full scraped output. Current federal
# coverage is ~300-400 rows across all 4 PDFs. Once provincials are added,
# the upper bound grows.
MIN_EXPECTED_ROWS = 100
MAX_EXPECTED_ROWS = 5000

# Sources whose published standards carry NO effective year anywhere in
# the payload (the OPA xlsx has no year cell; the FQD JSON API has no
# year field). The year is therefore a hand-maintained binding, kept in
# this ONE table so it cannot go stale silently: the parsers take the
# year as a required argument (no in-parser default), and
# ``check_year_bindings`` runs at the top of every orchestrator run,
# warning when a binding is one calendar year behind and FAILING the
# run when it is two behind. When a federation publishes revised
# standards, bump its entry here in the same commit as the fixture
# refresh. Sources that DO carry a year (CPU titles, MPA filename, NSPL
# per-year tabs, NLPA creation date) are not listed.
YEAR_BINDINGS: dict[str, int] = {
    "opa": 2026,
    "fqd": 2026,
}


class StaleYearBindingError(Exception):
    """A hand-maintained effective-year binding is too old to trust."""


def check_year_bindings(
    today: date | None = None,
    bindings: dict[str, int] | None = None,
) -> list[str]:
    """Return one warning per binding that is one year behind ``today``.

    Raise ``StaleYearBindingError`` for any binding two or more years
    behind. Provincial standards for competition year Y are published
    during Y-1, so a binding that still reads Y-2 in year Y means the
    federation has almost certainly revised twice since we last looked,
    and every row we emit under it is mislabelled.
    """
    today = today or date.today()
    bindings = YEAR_BINDINGS if bindings is None else bindings
    warnings: list[str] = []
    stale: list[str] = []
    for source, year in bindings.items():
        behind = today.year - year
        if behind >= 2:
            stale.append(f"{source}={year} ({behind} years behind {today.year})")
        elif behind == 1:
            warnings.append(
                f"{source} effective_year binding is {year}; it is now "
                f"{today.year}. Check whether the federation has revised "
                f"and bump base.YEAR_BINDINGS."
            )
    if stale:
        raise StaleYearBindingError(
            "effective_year bindings too old to trust, refusing to publish "
            "mislabelled rows: " + "; ".join(stale)
            + ". Bump data/scrapers/base.py YEAR_BINDINGS after checking "
            "the source."
        )
    for w in warnings:
        log.warning("%s", w)
    return warnings


def check_federal_coverage(rows: Iterable[dict], today: date | None = None) -> int:
    """Fail loudly if the CPU federal scrape has no rows for the current year.

    ``cpu.py`` recognises PDF titles per year and crawls a fixed list of
    landing pages, so a new season (a ``/2028qualifications`` page with new
    title wording) silently produces NO rows rather than wrong rows. By
    January of year Y the year-Y standards have been published for months,
    so their absence means the crawler needs a new landing URL or title
    pattern. Returns the newest federal year found.
    """
    today = today or date.today()
    years = {
        int(r["effective_year"]) for r in rows
        if r.get("level") in ("Nationals", "Regionals")
    }
    if not years:
        raise StaleYearBindingError("no CPU federal rows at all")
    newest = max(years)
    if newest < today.year:
        raise StaleYearBindingError(
            f"newest CPU federal effective_year is {newest} but it is "
            f"{today.year}; add the new season's landing URL and title "
            f"patterns to data/scrapers/cpu.py"
        )
    return newest


class ValidationError(Exception):
    """Raised when a scraped row or batch fails sanity checks."""


def validate_row(row: dict) -> None:
    """Validate a single scraped row. Raises ValidationError on failure."""
    if row["sex"] not in VALID_SEX:
        raise ValidationError(f"bad sex {row['sex']!r} in row {row!r}")
    if row["level"] not in VALID_LEVEL:
        raise ValidationError(f"bad level {row['level']!r} in row {row!r}")
    if row["region"] not in VALID_REGION:
        raise ValidationError(f"bad region {row['region']!r} in row {row!r}")
    if row.get("province") not in VALID_PROVINCE:
        raise ValidationError(f"bad province {row.get('province')!r} in row {row!r}")
    # Level=Provincials must be paired with a province; Nationals /
    # Regionals must have province=None.
    if row["level"] == "Provincials" and row.get("province") is None:
        raise ValidationError(f"Provincials row must have province set: {row!r}")
    if row["level"] != "Provincials" and row.get("province") is not None:
        raise ValidationError(
            f"non-Provincials row must not have province: {row!r}"
        )
    if row["division"] not in VALID_DIVISION:
        raise ValidationError(f"bad division {row['division']!r} in row {row!r}")
    if row["equipment"] not in VALID_EQUIPMENT:
        raise ValidationError(f"bad equipment {row['equipment']!r} in row {row!r}")
    if row["event"] not in VALID_EVENT:
        raise ValidationError(f"bad event {row['event']!r} in row {row!r}")
    allowed_wc = (
        VALID_WEIGHT_CLASSES_M if row["sex"] == "M" else VALID_WEIGHT_CLASSES_F
    )
    if row["weight_class"] not in allowed_wc:
        raise ValidationError(
            f"weight_class {row['weight_class']!r} not valid for sex {row['sex']!r}"
        )
    qt = row["qt"]
    if not isinstance(qt, (int, float)) or not (QT_MIN_KG <= qt <= QT_MAX_KG):
        raise ValidationError(f"qt {qt!r} outside bounds [{QT_MIN_KG}, {QT_MAX_KG}]")
    yr = row["effective_year"]
    if not isinstance(yr, int) or yr < 2020 or yr > 2100:
        raise ValidationError(f"effective_year {yr!r} looks wrong")


def validate_batch(rows: Sequence[dict]) -> None:
    """
    Validate a batch of rows. Checks per-row sanity plus:
      - batch size within expected bounds
      - no duplicate (sex, level, region, division, equipment, event,
        weight_class, effective_year) keys
    """
    if not (MIN_EXPECTED_ROWS <= len(rows) <= MAX_EXPECTED_ROWS):
        raise ValidationError(
            f"batch size {len(rows)} outside expected "
            f"[{MIN_EXPECTED_ROWS}, {MAX_EXPECTED_ROWS}]"
        )
    seen: set[tuple] = set()
    for row in rows:
        validate_row(row)
        key = (
            row["sex"], row["level"], row["region"], row.get("province"),
            row["division"], row["equipment"], row["event"],
            row["weight_class"], row["effective_year"],
        )
        if key in seen:
            raise ValidationError(f"duplicate row key {key}")
        seen.add(key)


def write_csv(rows: Iterable[dict], path: Path) -> int:
    """Write rows in CSV_FIELDS order to ``path``. Returns rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
            n += 1
    log.info("wrote %d rows to %s", n, path)
    return n


def read_csv(path: Path) -> list[dict]:
    """Read a qt_current.csv into a list of dicts. Used for diffing."""
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            if r.get("qt"):
                r["qt"] = float(r["qt"])
            if r.get("effective_year"):
                r["effective_year"] = int(r["effective_year"])
            if not r.get("region"):
                r["region"] = None
            rows.append(r)
    return rows
