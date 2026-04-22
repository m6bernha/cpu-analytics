"""QT coverage computation.

Ported from QTchanges.py with the only change being the data source: instead
of reading the 285 MB CSV and applying a pandas filter, we read a slim
pre-filtered slice from DuckDB into pandas and run the original per-row loop.

Outputs match `qt_coverage_results.csv` to 2 decimal places for the default
Canada/CPU/Raw/Tested/SBD scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from .data import get_cursor, is_qt_current_available
from .data_static.qt_by_division import QT_OVERRIDES, has_age_specific_qt
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION


# =========================
# ERA + WINDOW DEFINITIONS
# =========================

ERA_CUTOFF_2025 = pd.Timestamp("2025-01-01")
ERA_CUTOFF_2027 = pd.Timestamp("2027-01-01")

NATIONALS_MONTH = 3
NATIONALS_DAY = 1

NATIONALS_YEAR_BY_STANDARD = {
    "pre2025": 2024,
    "2025": 2025,
    "2027": 2027,
}


@dataclass(frozen=True)
class TimeWindow:
    name: str
    start: pd.Timestamp | None
    end: pd.Timestamp | None


def era_window_for_standard(standard_key: str) -> TimeWindow:
    if standard_key == "pre2025":
        return TimeWindow("pre2025", None, ERA_CUTOFF_2025)
    if standard_key == "2025":
        return TimeWindow("2025", ERA_CUTOFF_2025, ERA_CUTOFF_2027)
    if standard_key == "2027":
        return TimeWindow("2027", ERA_CUTOFF_2027, None)
    raise ValueError(f"Unknown standard_key: {standard_key}")


def window_24mo_to_nationals(standard_key: str) -> TimeWindow:
    year = NATIONALS_YEAR_BY_STANDARD[standard_key]
    cutoff = pd.Timestamp(year=year, month=NATIONALS_MONTH, day=NATIONALS_DAY)
    start = cutoff - pd.DateOffset(months=24)
    return TimeWindow(f"24mo_to_{year}_nats", start, cutoff)


def apply_time_window(df: pd.DataFrame, w: TimeWindow) -> pd.DataFrame:
    out = df
    if w.start is not None:
        out = out[out["Date"] >= w.start]
    if w.end is not None:
        out = out[out["Date"] < w.end]
    return out


# =========================
# CORE AGGREGATIONS
# =========================

def lifter_best_totals(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["Sex", "CanonicalWeightClass", "Name"], as_index=False)
        .agg(BestTotalKg=("TotalKg", "max"))
    )


def pct_meeting_qt(best_df: pd.DataFrame, qt_value: float) -> float:
    denom = len(best_df)
    if denom == 0:
        return np.nan
    num = (best_df["BestTotalKg"] >= qt_value).sum()
    return 100.0 * num / denom


# =========================
# LOADERS
# =========================

def _load_best_totals_per_era(
    conn,
    country: str = DEFAULT_COUNTRY,
    federation: str = "CPU",
    equipment: str = "Raw",
    tested: str = "Yes",
    event: str = "SBD",
    age_filter: str = "open",
) -> pd.DataFrame:
    """Per-lifter best TotalKg within each era + 24mo window, in SQL.

    Returns a tiny aggregated DataFrame (one row per lifter per window)
    instead of pulling the full scope into pandas. Much cheaper on the
    512 MB Render instance.

    Era windows:
      pre2025: Date < 2025-01-01
      era2025: 2025-01-01 <= Date < 2027-01-01
      era2027: Date >= 2027-01-01
      nat24_2024: 2022-03-01 <= Date < 2024-03-01 (24mo to 2024 nats)
      nat24_2025: 2023-03-01 <= Date < 2025-03-01
      nat24_2027: 2025-03-01 <= Date < 2027-03-01
    """
    clauses = [
        "Country = ?",
        "Federation = ?",
        "Equipment = ?",
        "Tested = ?",
        "Event = ?",
    ]
    params: list = [country, federation, equipment, tested, event]
    if age_filter == "open":
        clauses.append("Division = ?")
        params.append("Open")
    elif age_filter != "all":
        raise ValueError(f"Unknown age_filter: {age_filter}")
    where_sql = " AND ".join(clauses)

    sql = f"""
        SELECT
            Sex,
            CanonicalWeightClass AS WeightClass,
            Name,
            MAX(CASE WHEN Date < DATE '2025-01-01' THEN TotalKg END) AS best_pre2025,
            MAX(CASE WHEN Date >= DATE '2025-01-01' AND Date < DATE '2027-01-01' THEN TotalKg END) AS best_2025,
            MAX(CASE WHEN Date >= DATE '2027-01-01' THEN TotalKg END) AS best_2027,
            MAX(CASE WHEN Date >= DATE '2022-03-01' AND Date < DATE '2024-03-01' THEN TotalKg END) AS best_nat24_2024,
            MAX(CASE WHEN Date >= DATE '2023-03-01' AND Date < DATE '2025-03-01' THEN TotalKg END) AS best_nat24_2025,
            MAX(CASE WHEN Date >= DATE '2025-03-01' AND Date < DATE '2027-03-01' THEN TotalKg END) AS best_nat24_2027
        FROM openipf
        WHERE {where_sql}
        GROUP BY Sex, CanonicalWeightClass, Name
    """
    return conn.execute(sql, params).df()


# Kept for backwards compat with any external callers + the old test path.
def _load_scope(
    conn,
    country: str = DEFAULT_COUNTRY,
    federation: str = "CPU",
    equipment: str = "Raw",
    tested: str = "Yes",
    event: str = "SBD",
    age_filter: str = "open",
) -> pd.DataFrame:
    """Load the scope used for QT coverage.

    age_filter:
      "open"  -> Open only (Division == 'Open').
                 This is the correct denominator for the CPU QT spreadsheet,
                 which is Open-only. The old QTchanges.py output mixed all age
                 classes and is therefore wrong as an "Open-only" metric.
      "all"   -> no age filter (legacy, matches the old QTchanges output).

    Note on the filter column: BirthYearClass and AgeClass were considered but
    are too sparse in this dataset (56-76% NULL for CPU rows), and AgeClass
    doesn't even use the '24-39' literal. Division is federation-free-text in
    general, but for CPU specifically the empirical audit (2026-04) showed
    Division='Open' is consistently populated (21,516 rows all-time, 2,286 in
    the 2025 era, no NULLs). If we later extend to non-CPU federations, this
    filter will need to be federation-aware.

    Accepts a DuckDB cursor as first argument so the caller (request handler)
    controls the cursor lifetime. Do not create a new cursor inside this helper.
    """
    clauses = [
        "Country = ?",
        "Federation = ?",
        "Equipment = ?",
        "Tested = ?",
        "Event = ?",
    ]
    params: list = [country, federation, equipment, tested, event]

    if age_filter == "open":
        clauses.append("Division = ?")
        params.append("Open")
    elif age_filter != "all":
        raise ValueError(f"Unknown age_filter: {age_filter}")

    sql = (
        "SELECT Name, Sex, CanonicalWeightClass, TotalKg, Date "
        "FROM openipf WHERE " + " AND ".join(clauses)
    )
    return conn.execute(sql, params).df()


def _load_qt_standards(conn) -> pd.DataFrame:
    """Load QT standards. Cursor passed in by caller to share lifetime."""
    return conn.execute("SELECT * FROM qt_standards").df()


# =========================
# COMPUTATION
# =========================

def compute_coverage(
    country: str = DEFAULT_COUNTRY,
    federation: str = "CPU",
    equipment: str = "Raw",
    tested: str = "Yes",
    event: str = "SBD",
    age_filter: str = "open",
) -> pd.DataFrame:
    # One cursor for the whole computation; aggregation is done in SQL
    # so we only pull the per-lifter max-per-era table (~few thousand
    # rows) into pandas, not the full scope.
    conn = get_cursor()
    bests = _load_best_totals_per_era(
        conn, country, federation, equipment, tested, event, age_filter,
    )
    qt = _load_qt_standards(conn)

    results = []
    # Map standard_key -> (all-era column, 24mo column)
    era_cols = {
        "pre2025": ("best_pre2025", "best_nat24_2024"),
        "2025": ("best_2025", "best_nat24_2025"),
        "2027": ("best_2027", "best_nat24_2027"),
    }
    qt_cols = {"pre2025": "QT_pre2025", "2025": "QT_2025", "2027": "QT_2027"}

    for _, row in qt.iterrows():
        sex = row["Sex"]
        level = row["Level"]
        wc = row["WeightClass"]

        # Filter to matching sex + class. bests already has one row per lifter.
        df_sw = bests[
            (bests["Sex"] == sex) & (bests["WeightClass"].astype(str) == wc)
        ]

        out_row: dict = {"Sex": sex, "Level": level, "WeightClass": wc}

        for standard_key, (all_col, nat24_col) in era_cols.items():
            qt_value = row[qt_cols[standard_key]]
            if pd.isna(qt_value):
                out_row[f"Pct_AllEra_{standard_key}"] = np.nan
                out_row[f"Pct_24moToNationals_{standard_key}"] = np.nan
                continue

            # All-era: lifters who had any meet in the era with best >= QT
            era_bests = df_sw[all_col].dropna()
            out_row[f"Pct_AllEra_{standard_key}"] = (
                100.0 * (era_bests >= float(qt_value)).sum() / len(era_bests)
                if len(era_bests) > 0 else np.nan
            )

            # 24mo window
            nat24_bests = df_sw[nat24_col].dropna()
            out_row[f"Pct_24moToNationals_{standard_key}"] = (
                100.0 * (nat24_bests >= float(qt_value)).sum() / len(nat24_bests)
                if len(nat24_bests) > 0 else np.nan
            )

        qt_2027 = row["QT_2027"]
        if pd.isna(qt_2027):
            out_row["Pct_HypotheticalSqueeze_2027_using_2025era"] = np.nan
        else:
            era_2025_bests = df_sw["best_2025"].dropna()
            out_row["Pct_HypotheticalSqueeze_2027_using_2025era"] = (
                100.0 * (era_2025_bests >= float(qt_2027)).sum() / len(era_2025_bests)
                if len(era_2025_bests) > 0 else np.nan
            )

        results.append(out_row)

    out = pd.DataFrame(results)

    def wc_sort_key(s: str) -> float:
        s = str(s)
        if s.endswith("+"):
            try:
                return float(s.rstrip("+")) + 0.5
            except ValueError:
                return 9999.0
        try:
            return float(s)
        except ValueError:
            return 9999.0

    out = out.sort_values(
        ["Sex", "Level", "WeightClass"],
        key=lambda col: col.map(wc_sort_key) if col.name == "WeightClass" else col,
    )

    pct_cols = [c for c in out.columns if c.startswith("Pct_")]
    out[pct_cols] = out[pct_cols].round(2)

    return out


def get_qt_standards() -> pd.DataFrame:
    return _load_qt_standards(get_cursor())


# =========================
# BLOCK VIEW (Open-only, 3 cols)
# =========================

@lru_cache(maxsize=16)
def compute_blocks(
    country: str = DEFAULT_COUNTRY,
    federation: str = "CPU",
    equipment: str = "Raw",
    tested: str = "Yes",
    event: str = "SBD",
    division: str = "Open",
) -> dict:
    """Return the four-block spreadsheet view for a given age division.

    Columns per row:
      - weight_class
      - pct_pre2025:  lifters in pre-2025 era meeting QT_pre2025
      - pct_2025:     lifters in 2025-2026 era meeting QT_2025
      - pct_2027_today: lifters in 2025-2026 era meeting QT_2027 (hypothetical)

    For v1, only Open has real QT thresholds. Other divisions fall back to
    Open values (denominator and thresholds both Open) until the
    powerlifting.ca/qualifying-standards table is transcribed into
    `data_static.qt_by_division.QT_OVERRIDES`. The API response wraps this
    result with a `meta.using_open_fallback` flag so the frontend can show
    a "Open values shown, age-specific coming" banner.
    """
    # Future: when QT_OVERRIDES[division] is populated, swap the threshold
    # table here and switch the Division filter on the denominator. For now
    # everything resolves to the Open view.
    _ = has_age_specific_qt(division)  # noqa: F841 -- forward-compatible hook
    _ = QT_OVERRIDES  # noqa: F841 -- keep the import live for future wiring
    full = compute_coverage(
        country=country,
        federation=federation,
        equipment=equipment,
        tested=tested,
        event=event,
        age_filter="open",
    )

    slim = full[
        [
            "Sex",
            "Level",
            "WeightClass",
            "Pct_AllEra_pre2025",
            "Pct_AllEra_2025",
            "Pct_HypotheticalSqueeze_2027_using_2025era",
        ]
    ].rename(
        columns={
            "Pct_AllEra_pre2025": "pct_pre2025",
            "Pct_AllEra_2025": "pct_2025",
            "Pct_HypotheticalSqueeze_2027_using_2025era": "pct_2027_today",
        }
    )

    # Always return all four block keys so the frontend can iterate
    # BLOCK_ORDER without crashing on undefined.map.
    blocks: dict = {
        "M_Nationals": [],
        "M_Regionals": [],
        "F_Nationals": [],
        "F_Regionals": [],
    }
    for (sex, level), group in slim.groupby(["Sex", "Level"], observed=True):
        key = f"{sex}_{level}"
        blocks[key] = group[
            ["WeightClass", "pct_pre2025", "pct_2025", "pct_2027_today"]
        ].to_dict(orient="records")

    return blocks


# =========================
# LIVE-SCRAPE COVERAGE (2026+)
# =========================
#
# The functions below read from ``qt_current`` (CSV published weekly by
# the qt_refresh GHA workflow) rather than ``qt_standards`` (parquet
# derived from the vendored pre-2025 / 2025 CSV). They are additive;
# nothing above this marker reads from qt_current.
#
# Data model recap (see data/scrapers/base.CSV_FIELDS):
#   sex, level, region, division, equipment, event, weight_class,
#   qt, effective_year, source_pdf, fetched_at
#
# Scope: Classic + SBD only. The orchestrator filters other values out
# before the CSV is published, so downstream code doesn't need to re-check.


# OpenIPF uses the word "Raw" for what CPU calls "Classic". Mapping is
# applied only when querying the openipf view; qt_current stays in CPU
# terminology end-to-end.
_CPU_TO_OPENIPF_EQUIPMENT = {"Classic": "Raw", "Equipped": "Single-ply"}

# Sentinel for load_live_qt(region=...) so callers can distinguish:
#   region not passed -> no region filter (all regions)
#   region=None      -> filter to "region IS NULL" (2026 Regionals)
#   region="Eastern" -> filter to region = 'Eastern'
_UNSET = object()


def load_live_qt(
    conn,
    *,
    sex: str | None = None,
    level: str | None = None,
    effective_year: int | None = None,
    division: str | None = None,
    region=_UNSET,
    equipment: str | None = "Classic",
    event: str | None = "SBD",
) -> pd.DataFrame:
    """
    Read a slice of ``qt_current``. Scalar filters: arg is ``None`` -> skip.
    ``region`` is tri-state via the _UNSET sentinel:
      * not passed          -> no region filter (all regions)
      * region=None         -> filter to ``region IS NULL`` (2026 Regionals
                                 and any pre-split row)
      * region="Eastern"    -> equality filter
    """
    if not is_qt_current_available():
        return pd.DataFrame()

    clauses: list[str] = []
    params: list = []
    if sex is not None:
        clauses.append("sex = ?")
        params.append(sex)
    if level is not None:
        clauses.append("level = ?")
        params.append(level)
    if effective_year is not None:
        clauses.append("effective_year = ?")
        params.append(int(effective_year))
    if division is not None:
        clauses.append("division = ?")
        params.append(division)
    if equipment is not None:
        clauses.append("equipment = ?")
        params.append(equipment)
    if event is not None:
        clauses.append("event = ?")
        params.append(event)
    if region is None:
        clauses.append("(region IS NULL OR region = '')")
    elif region is not _UNSET:
        clauses.append("region = ?")
        params.append(region)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(f"SELECT * FROM qt_current{where}", params).df()


def get_live_qt_filters() -> dict:
    """Enumerate available filter values from qt_current.

    Returned shape::

        {
            "live_data_available": bool,
            "sexes": [...], "levels": [...], "regions": [...],
            "divisions": [...], "effective_years": [...],
            "fetched_at": "<iso>",
        }

    If live data isn't available, only ``live_data_available: false``
    is returned. The frontend falls back to the 4-block view in that
    case.
    """
    if not is_qt_current_available():
        return {"live_data_available": False}
    conn = get_cursor()
    df = conn.execute(
        "SELECT DISTINCT sex, level, region, division, effective_year, "
        "fetched_at FROM qt_current"
    ).df()
    # fetched_at should be identical across rows in a single publish, but
    # take the max to be safe.
    fetched_at = (
        df["fetched_at"].max() if "fetched_at" in df and not df.empty else None
    )

    def _uniq_sorted(col: str) -> list:
        if col not in df or df.empty:
            return []
        return sorted(df[col].dropna().unique().tolist())

    # Division needs a CPU-canonical order (not alphabetical).
    division_order = [
        "Sub-Junior", "Junior", "Open",
        "Master 1", "Master 2", "Master 3", "Master 4",
    ]
    divisions = [d for d in division_order if d in set(_uniq_sorted("division"))]

    return {
        "live_data_available": True,
        "sexes": _uniq_sorted("sex"),
        "levels": _uniq_sorted("level"),
        "regions": _uniq_sorted("region"),
        "divisions": divisions,
        "effective_years": [int(y) for y in _uniq_sorted("effective_year")],
        "fetched_at": fetched_at,
    }


def _wc_sort_value(s: str) -> float:
    s = str(s)
    if s.endswith("+"):
        try:
            return float(s.rstrip("+")) + 0.5
        except ValueError:
            return 9999.0
    try:
        return float(s)
    except ValueError:
        return 9999.0


def compute_live_coverage(
    *,
    sex: str,
    level: str,
    effective_year: int,
    division: str = "Open",
    region: str | None = None,
    equipment: str = "Classic",
    country: str = DEFAULT_COUNTRY,
    federation: str = "CPU",
    tested: str = "Yes",
    event: str = "SBD",
) -> pd.DataFrame:
    """
    Coverage rate per weight class for a single slice of the live QT
    table.

    Cohort: all lifters in the openipf scope matching the filters whose
    most recent SBD total falls in the 24-month window ending March 1
    of the ``effective_year``. E.g. ``effective_year=2026`` -> the
    qualifying window is ``[2024-03-01, 2026-03-01)``.

    Returns a DataFrame with columns: ``weight_class, qt, n_lifters,
    n_meeting_qt, pct_meeting_qt``. Empty if no QT rows match the
    filter.
    """
    conn = get_cursor()
    qt_df = load_live_qt(
        conn,
        sex=sex, level=level, effective_year=effective_year,
        division=division, equipment=equipment, event=event,
        region=region,  # None -> NULL, string -> equality, see _UNSET sentinel
    )
    if qt_df.empty:
        return pd.DataFrame(columns=[
            "weight_class", "qt", "n_lifters", "n_meeting_qt", "pct_meeting_qt",
        ])

    end = pd.Timestamp(year=int(effective_year), month=NATIONALS_MONTH, day=NATIONALS_DAY)
    start = end - pd.DateOffset(months=24)
    openipf_equipment = _CPU_TO_OPENIPF_EQUIPMENT.get(equipment, equipment)

    clauses = [
        "Country = ?", "Federation = ?", "Equipment = ?", "Tested = ?",
        "Event = ?", "Sex = ?", "Division = ?",
        "Date >= ?", "Date < ?",
    ]
    params = [
        country, federation, openipf_equipment, tested, event, sex, division,
        start.date(), end.date(),
    ]
    sql = (
        "SELECT CanonicalWeightClass, Name, MAX(TotalKg) AS best_total "
        "FROM openipf "
        f"WHERE {' AND '.join(clauses)} "
        "GROUP BY CanonicalWeightClass, Name"
    )
    bests = conn.execute(sql, params).df()

    results = []
    for _, qt_row in qt_df.iterrows():
        wc = str(qt_row["weight_class"])
        qt_value = float(qt_row["qt"])
        cohort = bests[bests["CanonicalWeightClass"].astype(str) == wc]
        n = int(len(cohort))
        meeting = int((cohort["best_total"] >= qt_value).sum()) if n > 0 else 0
        pct = round(100.0 * meeting / n, 2) if n > 0 else None
        results.append({
            "weight_class": wc,
            "qt": qt_value,
            "n_lifters": n,
            "n_meeting_qt": meeting,
            "pct_meeting_qt": pct,
        })
    out = pd.DataFrame(results)
    out = out.sort_values("weight_class", key=lambda s: s.map(_wc_sort_value))
    return out.reset_index(drop=True)
