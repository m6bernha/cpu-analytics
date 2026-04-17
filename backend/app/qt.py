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

from .data import get_cursor
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
