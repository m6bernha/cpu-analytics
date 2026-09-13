"""Cohort progression: average value change from first meet over time.

Supports three metrics via the `metric` parameter:
  - "total"      -- TotalKg (default, original behaviour)
  - "bodyweight" -- BodyweightKg
  - "goodlift"   -- Goodlift (GLP score)

The generalized compute_progression function routes to the right SQL column and
returns the same payload shape regardless of metric.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from .data import get_cursor
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION

Metric = Literal["total", "bodyweight", "goodlift"]

# Maps metric key -> (parquet column, human label for y-axis)
METRIC_COLS: dict[str, tuple[str, str]] = {
    "total":      ("TotalKg",      "Total (kg)"),
    "bodyweight": ("BodyweightKg", "Bodyweight (kg)"),
    "goodlift":   ("Goodlift",     "Goodlift (GLP)"),
}


# Canonical CPU age divisions mapped to the string values that actually
# appear in OpenIPF's free-text Division column for CPU meets. This keeps
# the frontend using friendly labels (Master 1, Sub-Junior) while the
# query handles federation-specific spelling drift.
CPU_DIVISION_ALIASES: dict[str, list[str]] = {
    "Youth 1": ["Youth 1", "Y1"],
    "Youth 2": ["Youth 2", "Y2"],
    "Youth 3": ["Youth 3", "Y3"],
    "Sub-Junior": ["Sub-Junior", "Sub-Juniors", "SJ"],
    "Junior": ["Junior", "Juniors", "Jr"],
    "Open": ["Open"],
    "Master 1": ["Master 1", "Masters 1", "M1", "Masters 40-49"],
    "Master 2": ["Master 2", "Masters 2", "M2", "Masters 50-59"],
    "Master 3": ["Master 3", "Masters 3", "M3", "Masters 60-69"],
    "Master 4": ["Master 4", "Masters 4", "M4", "Masters 70+", "Masters 70-79", "Masters 80+"],
}


X_AXIS_COLS = {
    "Meet #": ("MeetNumber", "Meet number (1 = first meet in scope)"),
    "Days": ("DaysFromFirst", "Days since first meet"),
    "Weeks": ("WeeksFromFirst", "Weeks since first meet"),
    "Months": ("MonthsFromFirst", "Months since first meet"),
    "Years": ("YearsFromFirst", "Years since first meet"),
    "Career quartile": (
        "CareerQuartile",
        "Career quartile (Q1 = first 25% of each lifter's meets)",
    ),
    "Bodyweight bucket": (
        "BodyweightBucket",
        "Bodyweight (kg, 10-kg bucket)",
    ),
}


# Age category bounds, ported from main.py:104-122. Used only when an
# age_category filter is requested. Note: the Age column is 71% NULL in this
# dataset; an age_category filter will silently drop those rows.
def age_to_category(age: float) -> str | float:
    if pd.isna(age):
        return np.nan
    if age < 18.5:
        return "Sub-Jr"
    if age < 23.5:
        return "Jr"
    if age < 39.5:
        return "Open"
    if age < 49.5:
        return "M1"
    if age < 59.5:
        return "M2"
    if age < 69.5:
        return "M3"
    return "M4"


def _empty_response(x_axis: str, metric: str = "total") -> dict[str, Any]:
    """Shape-complete empty response so the frontend TS types hold.

    All early-return branches in compute_progression must use this to avoid
    missing-key crashes when any filter combination produces zero rows.
    """
    _, y_label = METRIC_COLS.get(metric, METRIC_COLS["total"])
    return {
        "x_label": X_AXIS_COLS[x_axis][1],
        "x_axis": x_axis,
        "metric": metric,
        "y_label": y_label,
        "points": [],
        "trend": None,
        "projection": None,
        "n_lifters": 0,
        "n_meets": 0,
        "n_lifters_before_age_filter": 0,
        "n_all_lifters": 0,
        "avg_first_value": None,
    }


def _build_filter_clauses(
    sex: str | None,
    equipment: str | None,
    tested: str | None,
    event: str | None,
    federation: str | None,
    country: str | None,
    parent_federation: str | None,
    weight_class: str | None,
    division: str | None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    def eq(col: str, val: str | None) -> None:
        if val and val != "All":
            clauses.append(f"{col} = ?")
            params.append(val)

    eq("Sex", sex)

    # Equipment: "Equipped" is a UI shortcut that matches any non-Raw
    # equipment (CPU bifurcates Classic Raw vs Equipped). OpenIPF stores
    # Single-ply / Wraps / Multi-ply separately; we OR them.
    if equipment == "Equipped":
        clauses.append("Equipment IN ('Single-ply', 'Wraps', 'Multi-ply', 'Unlimited')")
    else:
        eq("Equipment", equipment)

    eq("Tested", tested)
    eq("Event", event)
    eq("Federation", federation)
    eq("Country", country)
    eq("ParentFederation", parent_federation)

    # Division: CPU canonical labels map to one or more OpenIPF free-text
    # values. "Master 1" matches "Master 1", "Masters 1", "M1", "Masters 40-49", etc.
    if division and division != "All":
        aliases = CPU_DIVISION_ALIASES.get(division)
        if aliases:
            placeholders = ",".join("?" * len(aliases))
            clauses.append(f"Division IN ({placeholders})")
            params.extend(aliases)
        else:
            # Unknown label -- fall through to exact match
            clauses.append("Division = ?")
            params.append(division)

    if weight_class and weight_class != "Overall":
        clauses.append("CanonicalWeightClass = ?")
        params.append(weight_class)

    return clauses, params


# ---------------------------------------------------------------------------
# Shared cohort filters (extracted 2026-09-11). compute_progression and
# compute_lift_progression carried two near-identical copies of each of
# these; a fix landing in one and not the other was the failure mode.
# All three are behaviour-preserving extractions of the previous inline code.
# ---------------------------------------------------------------------------

def _apply_gap_filter(df: pd.DataFrame, max_gap_months: int | None) -> pd.DataFrame:
    """Drop every lifter with any inter-meet gap longer than max_gap_months.

    "Comeback" lifters contaminate progression curves because their
    long-break gains get averaged into the same x-buckets as continuous
    competitors. No-op when the filter is off or the frame is empty.
    """
    if max_gap_months is None or df.empty:
        return df
    max_gap_days = max_gap_months * 30.44
    df = df.sort_values(["Name", "DaysFromFirst"])
    df["_prev_days"] = df.groupby("Name")["DaysFromFirst"].shift(1)
    df["_gap"] = df["DaysFromFirst"] - df["_prev_days"]
    max_gaps = df.groupby("Name")["_gap"].max()
    long_gap_names = set(max_gaps[max_gaps > max_gap_days].index)
    if long_gap_names:
        df = df[~df["Name"].isin(long_gap_names)]
    return df.drop(columns=["_prev_days", "_gap"])


def _apply_same_class_filter(df: pd.DataFrame, same_class_only: bool) -> pd.DataFrame:
    """Keep only lifters whose CanonicalWeightClass never changed in scope.

    ClassCount is the SQL-side COUNT(DISTINCT CanonicalWeightClass) per
    lifter; a frame without that column is passed through untouched.
    """
    if not same_class_only or df.empty or "ClassCount" not in df.columns:
        return df
    return df[df["ClassCount"] == 1]


def _apply_age_filter_and_rebaseline(
    df: pd.DataFrame,
    age_category: str | None,
    value_to_diff: dict[str, str],
) -> pd.DataFrame:
    """Filter rows to one age category, then re-anchor each lifter's deltas.

    Age is sparse and the category boundaries align with no column literal,
    so the filter runs in pandas. After dropping rows outside the category
    every lifter MUST be rebaselined to their first SURVIVING meet: an Open
    lifter who started as a Junior would otherwise have deltas measured
    from an invisible Junior-era baseline, inflating the Open cohort curve.

    ``value_to_diff`` maps each value column to the diff column it feeds
    (``{"Value": "DiffFromFirst"}`` for the total/bodyweight/GLP metric,
    the three Best3*Kg -> *Diff pairs for the per-lift view). Lifters left
    with fewer than two meets in the category are dropped. When the frame
    carries ``MeetNumber`` it is renumbered within the category.
    """
    if not age_category or age_category == "All":
        return df
    df["AgeCategory"] = df["Age"].apply(age_to_category)
    df = df[df["AgeCategory"] == age_category]
    if df.empty:
        return df

    first_idx = df.groupby("Name")["DaysFromFirst"].idxmin()
    rename = {col: f"_First_{col}" for col in value_to_diff}
    rename["DaysFromFirst"] = "_FirstDays"
    first_vals = (
        df.loc[first_idx, ["Name", *value_to_diff, "DaysFromFirst"]]
        .rename(columns=rename)
    )
    df = df.merge(first_vals, on="Name")
    for col, diff_col in value_to_diff.items():
        df[diff_col] = df[col] - df[f"_First_{col}"]
    df["DaysFromFirst"] = df["DaysFromFirst"] - df["_FirstDays"]
    if "MeetNumber" in df.columns:
        df["MeetNumber"] = df.groupby("Name").cumcount() + 1
    meet_counts = df.groupby("Name")["DaysFromFirst"].transform("count")
    df = df[meet_counts >= 2]
    return df.drop(columns=[*rename.values()])


def compute_progression(
    sex: str | None = None,
    equipment: str | None = None,
    tested: str | None = None,
    event: str | None = None,
    federation: str | None = None,
    country: str | None = DEFAULT_COUNTRY,
    parent_federation: str | None = DEFAULT_PARENT_FEDERATION,
    weight_class: str | None = None,
    division: str | None = None,
    age_category: str | None = None,
    x_axis: str = "Days",
    metric: str = "total",
    min_lifters_for_trend: int = 5,
    max_gap_months: int | None = None,
    same_class_only: bool = False,
) -> dict[str, Any]:
    """Return mean value change from first meet over time for the cohort.

    metric controls which column is tracked:
      "total"      -- TotalKg (default)
      "bodyweight" -- BodyweightKg
      "goodlift"   -- Goodlift (GLP score)

    Returns:
        {
          "x_label": str,
          "x_axis": str,
          "metric": str,
          "y_label": str,
          "points": [{"x": int, "y": float, "lifter_count": int}, ...],
          "trend": {"slope": float, "intercept": float, "unit": str} | None,
          "n_lifters": int,
          "n_meets": int,
          "avg_first_value": float | None,
        }
    """
    if x_axis not in X_AXIS_COLS:
        raise ValueError(f"Unknown x_axis: {x_axis}. Use one of {list(X_AXIS_COLS)}")
    if metric not in METRIC_COLS:
        raise ValueError(f"Unknown metric: {metric}. Use one of {list(METRIC_COLS)}")

    val_col, y_label = METRIC_COLS[metric]

    clauses, params = _build_filter_clauses(
        sex, equipment, tested, event, federation, country, parent_federation,
        weight_class, division,
    )
    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    # Pull a slim slice. Doing the windowing + grouping in DuckDB SQL keeps
    # this fast even for big scopes (e.g. all-Canada with no class filter).
    # CanonicalWeightClass is included so we can detect class changes for
    # the same_class_only filter.
    # Order by TotalKg DESC as the tiebreaker so behaviour is stable regardless
    # of metric -- for bodyweight/goodlift meets, TotalKg may be null (bench-only)
    # but the primary sort is Date which handles most cases.
    sql = f"""
        WITH filtered AS (
            SELECT Name, Date, {val_col}, TotalKg, BodyweightKg, Age, MeetName, CanonicalWeightClass
            FROM openipf
            {where_sql}
        ),
        ranked AS (
            SELECT
                Name,
                Date,
                {val_col},
                BodyweightKg,
                Age,
                CanonicalWeightClass,
                ROW_NUMBER() OVER (PARTITION BY Name ORDER BY Date, TotalKg DESC NULLS LAST, MeetName) AS MeetNumber,
                FIRST_VALUE({val_col}) OVER (PARTITION BY Name ORDER BY Date, TotalKg DESC NULLS LAST, MeetName) AS FirstValue,
                MIN(Date) OVER (PARTITION BY Name) AS FirstDate,
                COUNT(*) OVER (PARTITION BY Name) AS MeetCount,
                COUNT(DISTINCT CanonicalWeightClass) OVER (PARTITION BY Name) AS ClassCount
            FROM filtered
        )
        SELECT
            Name,
            Age,
            {val_col} AS Value,
            BodyweightKg,
            CanonicalWeightClass,
            MeetNumber,
            ClassCount,
            DATEDIFF('day', FirstDate, Date) AS DaysFromFirst,
            ({val_col} - FirstValue) AS DiffFromFirst
        FROM ranked
        WHERE MeetCount >= 2
          AND {val_col} IS NOT NULL
          AND FirstValue IS NOT NULL
    """
    conn = get_cursor()
    df = conn.execute(sql, params).df()

    # Survivorship stats: count ALL lifters in scope (including 1-meet)
    # and compute the average first-meet value, so the frontend can show
    # retention rate and day-0 population context.
    all_lifters_sql = f"""
        WITH filtered AS (
            SELECT Name, Date, {val_col}, TotalKg, MeetName
            FROM openipf
            {where_sql}
        ),
        first_meets AS (
            SELECT DISTINCT ON (Name) Name, {val_col} AS FirstValue
            FROM filtered
            ORDER BY Name, Date, TotalKg DESC NULLS LAST, MeetName
        )
        SELECT
            COUNT(*) AS total_lifters,
            AVG(FirstValue) AS avg_first_value
        FROM first_meets
    """
    surv_row = conn.execute(all_lifters_sql, params).fetchone()
    n_all_lifters = int(surv_row[0]) if surv_row else 0
    avg_first_value = round(float(surv_row[1]), 1) if surv_row and surv_row[1] is not None else None

    df = _apply_gap_filter(df, max_gap_months)
    if df.empty:
        return _empty_response(x_axis, metric)

    # Track pre-age-filter count BEFORE same_class_only + age filter so the
    # "dropped due to missing Age" message isn't contaminated by the
    # same-class filter's drops.
    n_lifters_before_age_filter = int(df["Name"].nunique())

    df = _apply_same_class_filter(df, same_class_only)

    # Age filter + rebaseline to the first surviving meet (see helper).
    df = _apply_age_filter_and_rebaseline(df, age_category, {"Value": "DiffFromFirst"})
    if df.empty:
        return {
            "x_label": X_AXIS_COLS[x_axis][1],
            "x_axis": x_axis,
            "metric": metric,
            "y_label": y_label,
            "points": [],
            "trend": None,
            "n_lifters": 0,
            "n_meets": 0,
        }

    # Derive the requested x-axis column from DaysFromFirst.
    df["WeeksFromFirst"] = (df["DaysFromFirst"] / 7).round().astype(int)
    df["MonthsFromFirst"] = (df["DaysFromFirst"] / 30.44).round().astype(int)
    df["YearsFromFirst"] = (df["DaysFromFirst"] / 365.25).round().astype(int)
    # Career quartile: for each lifter, split their career span (first -> last
    # meet) into four equal time windows and tag each meet with its quartile
    # 1..4. Lifters with all meets on the same day (career_span = 0) fall
    # into Q1 by default. The ≥2 meet filter above guarantees len >= 2 per
    # lifter but does not guarantee span > 0.
    career_span = df.groupby("Name")["DaysFromFirst"].transform("max")
    # Avoid div-by-zero: where span is 0, put every meet in Q1.
    with np.errstate(divide="ignore", invalid="ignore"):
        raw_q = np.where(
            career_span > 0,
            df["DaysFromFirst"].to_numpy(dtype=float) / career_span.to_numpy(dtype=float),
            0.0,
        )
    df["CareerQuartile"] = np.clip(
        np.floor(raw_q * 4).astype(int) + 1, 1, 4,
    )
    # Bodyweight bucket: 10 kg bucket of the lifter's bodyweight at each
    # meet (NOT starting bodyweight — this answers "what does avg progression
    # look like at each bodyweight band a lifter passes through"). Rows
    # missing BodyweightKg are dropped from the bucket axis only; they
    # remain valid for time-based axes.
    if x_axis == "Bodyweight bucket":
        df = df[df["BodyweightKg"].notna() & (df["BodyweightKg"] > 0)]
        if df.empty:
            return _empty_response(x_axis, metric)
        df["BodyweightBucket"] = (
            (df["BodyweightKg"].astype(float) // 10) * 10
        ).astype(int)

    x_col, x_label = X_AXIS_COLS[x_axis]
    grouped = (
        df.groupby(x_col)
        .agg(
            y=("DiffFromFirst", "mean"),
            std=("DiffFromFirst", "std"),
            lifter_count=("Name", "nunique"),
        )
        .reset_index()
        .sort_values(x_col)
        .rename(columns={x_col: "x"})
    )
    # Single-lifter buckets have NaN std; fill with 0.
    grouped["std"] = grouped["std"].fillna(0)

    # Trendline: WEIGHTED linear fit on points with enough lifters.
    # Each x-bucket is weighted by its lifter count so dense early years
    # dominate the slope and sparse tail years don't pull it around.
    trend = None
    fit = grouped[grouped["lifter_count"] >= min_lifters_for_trend]
    if len(fit) >= 2:
        x_arr = fit["x"].to_numpy(dtype=float)
        y_arr = fit["y"].to_numpy(dtype=float)
        w_arr = fit["lifter_count"].to_numpy(dtype=float)
        # Weighted OLS via numpy: polyfit accepts a `w` parameter (sqrt of weights)
        coeffs = np.polyfit(x_arr, y_arr, deg=1, w=np.sqrt(w_arr))
        # Weighted R-squared
        y_pred = np.polyval(coeffs, x_arr)
        y_mean = np.average(y_arr, weights=w_arr)
        ss_res = float(np.sum(w_arr * (y_arr - y_pred) ** 2))
        ss_tot = float(np.sum(w_arr * (y_arr - y_mean) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        unit_map = {
            "Meet #": "meet",
            "Days": "day",
            "Weeks": "week",
            "Months": "month",
            "Years": "year",
            "Career quartile": "quartile",
            "Bodyweight bucket": "10kg-bucket",
        }
        # Residual std for projection confidence band
        residuals = y_arr - y_pred
        residual_std = float(np.std(residuals))

        trend = {
            "slope": float(coeffs[0]),
            "intercept": float(coeffs[1]),
            "unit": unit_map[x_axis],
            "r_squared": round(r_squared, 4),
            "residual_std": round(residual_std, 2),
        }

    # Cohort projection: extend the trendline forward with confidence band.
    # Skip for ordinal axes that don't represent forward-in-time motion:
    #   - "Career quartile": Q4 is by definition the end of a lifter's career.
    #   - "Bodyweight bucket": bodyweight is not a time variable; a lifter
    #     can move up or down classes, so "next bucket" isn't a projection.
    projection = None
    _ORDINAL_AXES = {"Career quartile", "Bodyweight bucket"}
    if trend is not None and x_axis not in _ORDINAL_AXES:
        last_x = int(grouped["x"].max())
        project_steps = 4
        projection_points = []
        for i in range(1, project_steps + 1):
            future_x = last_x + i
            pred_y = trend["slope"] * future_x + trend["intercept"]
            # Confidence widens with distance from data center
            band = trend["residual_std"] * (1 + i * 0.2)
            projection_points.append({
                "x": future_x,
                "y": round(pred_y, 2),
                "upper": round(pred_y + band, 2),
                "lower": round(pred_y - band, 2),
            })
        projection = {
            "points": projection_points,
            "unit": trend["unit"],
        }

    points = [
        {
            "x": int(row.x),
            "y": float(row.y),
            "std": float(row.std),
            "lifter_count": int(row.lifter_count),
        }
        for row in grouped.itertuples(index=False)
    ]

    return {
        "x_label": x_label,
        "x_axis": x_axis,
        "metric": metric,
        "y_label": y_label,
        "points": points,
        "trend": trend,
        "n_lifters": int(df["Name"].nunique()),
        "n_meets": int(len(df)),
        "n_lifters_before_age_filter": n_lifters_before_age_filter,
        "n_all_lifters": n_all_lifters,
        "avg_first_value": avg_first_value,
        "projection": projection,
    }


# =============================================================================
# Per-lift progression (squat, bench, deadlift individually)
# =============================================================================

LIFT_COLS = {
    "squat": "Best3SquatKg",
    "bench": "Best3BenchKg",
    "deadlift": "Best3DeadliftKg",
}


def _empty_lift_response(x_axis: str) -> dict[str, Any]:
    return {
        "x_label": X_AXIS_COLS[x_axis][1],
        "lifts": {"squat": [], "bench": [], "deadlift": []},
        "n_lifters": 0,
    }


def compute_lift_progression(
    sex: str | None = None,
    equipment: str | None = None,
    tested: str | None = None,
    event: str | None = None,
    federation: str | None = None,
    country: str | None = DEFAULT_COUNTRY,
    parent_federation: str | None = DEFAULT_PARENT_FEDERATION,
    weight_class: str | None = None,
    division: str | None = None,
    age_category: str | None = None,
    x_axis: str = "Years",
    max_gap_months: int | None = None,
    same_class_only: bool = False,
) -> dict[str, Any]:
    """Return per-lift mean change from first meet for S/B/D.

    Returns:
        {
          "x_label": str,
          "lifts": {
            "squat": [{"x": int, "y": float, "lifter_count": int}, ...],
            "bench": [...],
            "deadlift": [...],
          },
          "n_lifters": int,
        }
    """
    if x_axis not in X_AXIS_COLS:
        raise ValueError(f"Unknown x_axis: {x_axis}")

    # The per-lift function only supports time-derived axes today. The ordinal
    # axes (Career quartile, Bodyweight bucket) require additional derivation
    # (career-span groupby OR a BodyweightKg SELECT) that this function does
    # not perform. Degrade gracefully so the per-lift toggle doesn't crash
    # when a user picks one of these axes; the frontend already gates
    # axis-aware features off of the empty response shape. See plan
    # where-did-we-leave-elegant-sifakis.md stage 2c for the support gap.
    _UNSUPPORTED_PER_LIFT_AXES = {"Career quartile", "Bodyweight bucket"}
    if x_axis in _UNSUPPORTED_PER_LIFT_AXES:
        return _empty_lift_response(x_axis)

    clauses, params = _build_filter_clauses(
        sex, equipment, tested, event, federation, country, parent_federation,
        weight_class, division,
    )
    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    sql = f"""
        WITH filtered AS (
            SELECT Name, Date, Age, CanonicalWeightClass,
                   Best3SquatKg, Best3BenchKg, Best3DeadliftKg, MeetName
            FROM openipf
            {where_sql}
        ),
        ranked AS (
            SELECT
                Name, Date, Age, CanonicalWeightClass,
                Best3SquatKg, Best3BenchKg, Best3DeadliftKg,
                FIRST_VALUE(Best3SquatKg) OVER w AS FirstSquat,
                FIRST_VALUE(Best3BenchKg) OVER w AS FirstBench,
                FIRST_VALUE(Best3DeadliftKg) OVER w AS FirstDeadlift,
                MIN(Date) OVER (PARTITION BY Name) AS FirstDate,
                COUNT(*) OVER (PARTITION BY Name) AS MeetCount,
                COUNT(DISTINCT CanonicalWeightClass) OVER (PARTITION BY Name) AS ClassCount
            FROM filtered
            WINDOW w AS (PARTITION BY Name ORDER BY Date, Best3SquatKg DESC NULLS LAST, MeetName)
        )
        SELECT
            Name,
            Age,
            CanonicalWeightClass,
            ClassCount,
            Best3SquatKg,
            Best3BenchKg,
            Best3DeadliftKg,
            DATEDIFF('day', FirstDate, Date) AS DaysFromFirst,
            (Best3SquatKg - FirstSquat) AS SquatDiff,
            (Best3BenchKg - FirstBench) AS BenchDiff,
            (Best3DeadliftKg - FirstDeadlift) AS DeadliftDiff
        FROM ranked
        WHERE MeetCount >= 2
          AND Best3SquatKg IS NOT NULL
          AND Best3BenchKg IS NOT NULL
          AND Best3DeadliftKg IS NOT NULL
    """
    conn = get_cursor()
    df = conn.execute(sql, params).df()

    if df.empty:
        return _empty_lift_response(x_axis)

    # Same three cohort filters as compute_progression, via the shared helpers.
    df = _apply_gap_filter(df, max_gap_months)
    if df.empty:
        return _empty_lift_response(x_axis)
    df = _apply_same_class_filter(df, same_class_only)
    if df.empty:
        return _empty_lift_response(x_axis)
    df = _apply_age_filter_and_rebaseline(
        df, age_category,
        {"Best3SquatKg": "SquatDiff", "Best3BenchKg": "BenchDiff", "Best3DeadliftKg": "DeadliftDiff"},
    )
    if df.empty:
        return _empty_lift_response(x_axis)

    # Derive time columns
    df["WeeksFromFirst"] = (df["DaysFromFirst"] / 7).round().astype(int)
    df["MonthsFromFirst"] = (df["DaysFromFirst"] / 30.44).round().astype(int)
    df["YearsFromFirst"] = (df["DaysFromFirst"] / 365.25).round().astype(int)

    x_col, x_label = X_AXIS_COLS[x_axis]

    lifts_result: dict[str, list[dict[str, Any]]] = {}
    diff_cols = {"squat": "SquatDiff", "bench": "BenchDiff", "deadlift": "DeadliftDiff"}

    for lift_key, diff_col in diff_cols.items():
        grouped = (
            df.groupby(x_col)
            .agg(y=(diff_col, "mean"), lifter_count=("Name", "nunique"))
            .reset_index()
            .sort_values(x_col)
            .rename(columns={x_col: "x"})
        )
        # Filter sparse points
        grouped = grouped[grouped["lifter_count"] >= 2]
        lifts_result[lift_key] = [
            {"x": int(r.x), "y": round(float(r.y), 2), "lifter_count": int(r.lifter_count)}
            for r in grouped.itertuples(index=False)
        ]

    return {
        "x_label": x_label,
        "lifts": lifts_result,
        "n_lifters": int(df["Name"].nunique()),
    }
