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
from pathlib import Path
from typing import Iterable, Sequence

log = logging.getLogger(__name__)

# Column order for qt_current.csv. Scrapers emit dicts using these keys
# (minus source_pdf / fetched_at, which the orchestrator adds).
CSV_FIELDS = (
    "sex",
    "level",
    "region",
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
VALID_LEVEL = ("Nationals", "Regionals")
VALID_REGION = (None, "Western/Central", "Eastern")
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
            row["sex"], row["level"], row["region"], row["division"],
            row["equipment"], row["event"], row["weight_class"],
            row["effective_year"],
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
