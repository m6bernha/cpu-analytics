"""QT coverage computation.

Ported from QTchanges.py with the only change being the data source: instead
of reading the 285 MB CSV and applying a pandas filter, we read a slim
pre-filtered slice from DuckDB into pandas and run the original per-row loop.

Outputs match `qt_coverage_results.csv` to 2 decimal places for the default
Canada/CPU/Raw/Tested/SBD scope.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import get_conn
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

def _load_scope(
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
    """
    conn = get_conn()

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


def _load_qt_standards() -> pd.DataFrame:
    conn = get_conn()
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
    openipf = _load_scope(country, federation, equipment, tested, event, age_filter)
    qt = _load_qt_standards()

    results = []
    standards = [
        ("pre2025", "QT_pre2025"),
        ("2025", "QT_2025"),
        ("2027", "QT_2027"),
    ]

    for _, row in qt.iterrows():
        sex = row["Sex"]
        level = row["Level"]
        wc = row["WeightClass"]

        df_sw = openipf[
            (openipf["Sex"] == sex) & (openipf["CanonicalWeightClass"].astype(str) == wc)
        ].copy()

        out_row: dict = {"Sex": sex, "Level": level, "WeightClass": wc}

        for standard_key, qt_col in standards:
            qt_value = row[qt_col]
            if pd.isna(qt_value):
                out_row[f"Pct_AllEra_{standard_key}"] = np.nan
                out_row[f"Pct_24moToNationals_{standard_key}"] = np.nan
                continue

            era_w = era_window_for_standard(standard_key)
            df_era = apply_time_window(df_sw, era_w)
            best_era = lifter_best_totals(df_era)
            out_row[f"Pct_AllEra_{standard_key}"] = pct_meeting_qt(best_era, float(qt_value))

            w24 = window_24mo_to_nationals(standard_key)
            df_24 = apply_time_window(df_sw, w24)
            best_24 = lifter_best_totals(df_24)
            out_row[f"Pct_24moToNationals_{standard_key}"] = pct_meeting_qt(best_24, float(qt_value))

        qt_2027 = row["QT_2027"]
        if pd.isna(qt_2027):
            out_row["Pct_HypotheticalSqueeze_2027_using_2025era"] = np.nan
        else:
            era_2025 = era_window_for_standard("2025")
            df_2025era = apply_time_window(df_sw, era_2025)
            best_2025era = lifter_best_totals(df_2025era)
            out_row["Pct_HypotheticalSqueeze_2027_using_2025era"] = pct_meeting_qt(
                best_2025era, float(qt_2027)
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
    return _load_qt_standards()


# =========================
# BLOCK VIEW (Open-only, 3 cols)
# =========================

def compute_blocks(
    country: str = DEFAULT_COUNTRY,
    federation: str = "CPU",
    equipment: str = "Raw",
    tested: str = "Yes",
    event: str = "SBD",
) -> dict:
    """Return the four-block Open-only spreadsheet view.

    Columns per row:
      - weight_class
      - pct_pre2025:  Open lifters in pre-2025 era meeting QT_pre2025
      - pct_2025:     Open lifters in 2025-2026 era meeting QT_2025
      - pct_2027_today: Open lifters in 2025-2026 era meeting QT_2027 (hypothetical)

    This is the correct denominator for the CPU QT spreadsheet, which is
    Open-only. The old QTchanges.py output mixed all age classes.
    """
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
