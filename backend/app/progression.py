"""Cohort progression: average TotalDiffFromFirst over time, with optional trendline.

Generalized from the original main.py:193-237 `compute_series` so every filter is
a parameter and the underlying data is queried from DuckDB instead of a global
DataFrame. The matplotlib UI is gone — this returns plain rows the frontend
plots with Recharts.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .data import get_conn
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION


X_AXIS_COLS = {
    "Meet #": ("MeetNumber", "Meet number (1 = first meet in scope)"),
    "Days": ("DaysFromFirst", "Days since first meet"),
    "Weeks": ("WeeksFromFirst", "Weeks since first meet"),
    "Months": ("MonthsFromFirst", "Months since first meet"),
    "Years": ("YearsFromFirst", "Years since first meet"),
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
    eq("Equipment", equipment)
    eq("Tested", tested)
    eq("Event", event)
    eq("Federation", federation)
    eq("Country", country)
    eq("ParentFederation", parent_federation)
    eq("Division", division)

    if weight_class and weight_class != "Overall":
        clauses.append("CanonicalWeightClass = ?")
        params.append(weight_class)

    return clauses, params


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
    min_lifters_for_trend: int = 5,
) -> dict[str, Any]:
    """Return mean TotalDiffFromFirst over time for the cohort defined by filters.

    Returns:
        {
          "x_label": str,
          "x_axis": str,
          "points": [{"x": int, "y": float, "lifter_count": int}, ...],
          "trend": {"slope": float, "intercept": float, "unit": str} | None,
          "n_lifters": int,
          "n_meets": int,
        }
    """
    if x_axis not in X_AXIS_COLS:
        raise ValueError(f"Unknown x_axis: {x_axis}. Use one of {list(X_AXIS_COLS)}")

    clauses, params = _build_filter_clauses(
        sex, equipment, tested, event, federation, country, parent_federation,
        weight_class, division,
    )
    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    # Pull a slim slice. Doing the windowing + grouping in DuckDB SQL keeps
    # this fast even for big scopes (e.g. all-Canada with no class filter).
    sql = f"""
        WITH filtered AS (
            SELECT Name, Date, TotalKg, Age, MeetName
            FROM openipf
            {where_sql}
        ),
        ranked AS (
            SELECT
                Name,
                Date,
                TotalKg,
                Age,
                ROW_NUMBER() OVER (PARTITION BY Name ORDER BY Date, TotalKg DESC, MeetName) AS MeetNumber,
                FIRST_VALUE(TotalKg) OVER (PARTITION BY Name ORDER BY Date, TotalKg DESC, MeetName) AS FirstTotal,
                MIN(Date) OVER (PARTITION BY Name) AS FirstDate,
                COUNT(*) OVER (PARTITION BY Name) AS MeetCount
            FROM filtered
        )
        SELECT
            Name,
            Age,
            TotalKg,
            MeetNumber,
            DATEDIFF('day', FirstDate, Date) AS DaysFromFirst,
            (TotalKg - FirstTotal) AS TotalDiffFromFirst
        FROM ranked
        WHERE MeetCount >= 2
    """
    conn = get_conn()
    df = conn.execute(sql, params).df()

    if df.empty:
        return {
            "x_label": X_AXIS_COLS[x_axis][1],
            "x_axis": x_axis,
            "points": [],
            "trend": None,
            "n_lifters": 0,
            "n_meets": 0,
        }

    # Track pre-age-filter count so the frontend can show how much data
    # the sparse Age column costs the user.
    n_lifters_before_age_filter = int(df["Name"].nunique())

    # Apply optional age category filter in pandas — Age is sparse and the
    # category boundaries don't align with any column literal in the dataset.
    #
    # IMPORTANT: after filtering, we recompute TotalDiffFromFirst and
    # DaysFromFirst relative to the first meet *within the surviving rows*.
    # Without this, an Open lifter who started as Junior sees their delta
    # measured from the invisible Junior-era baseline, which produces
    # inflated progression curves for the Open cohort.
    if age_category and age_category != "All":
        df["AgeCategory"] = df["Age"].apply(age_to_category)
        df = df[df["AgeCategory"] == age_category]
        if df.empty:
            return {
                "x_label": X_AXIS_COLS[x_axis][1],
                "x_axis": x_axis,
                "points": [],
                "trend": None,
                "n_lifters": 0,
                "n_meets": 0,
            }

        # Recompute baseline from first meet that survived the age filter.
        first_idx = df.groupby("Name")["DaysFromFirst"].idxmin()
        first_totals = (
            df.loc[first_idx, ["Name", "TotalKg", "DaysFromFirst"]]
            .rename(columns={"TotalKg": "_FirstTotal", "DaysFromFirst": "_FirstDays"})
        )
        df = df.merge(first_totals, on="Name")
        df["TotalDiffFromFirst"] = df["TotalKg"] - df["_FirstTotal"]
        df["DaysFromFirst"] = df["DaysFromFirst"] - df["_FirstDays"]
        # Re-number meets within this age category
        df["MeetNumber"] = df.groupby("Name").cumcount() + 1
        # Drop lifters with only one meet in this category
        meet_counts = df.groupby("Name")["MeetNumber"].transform("max")
        df = df[meet_counts >= 2]
        df = df.drop(columns=["_FirstTotal", "_FirstDays"])
        if df.empty:
            return {
                "x_label": X_AXIS_COLS[x_axis][1],
                "x_axis": x_axis,
                "points": [],
                "trend": None,
                "n_lifters": 0,
                "n_meets": 0,
            }

    # Derive the requested x-axis column from DaysFromFirst.
    df["WeeksFromFirst"] = (df["DaysFromFirst"] / 7).round().astype(int)
    df["MonthsFromFirst"] = (df["DaysFromFirst"] / 30.44).round().astype(int)
    df["YearsFromFirst"] = (df["DaysFromFirst"] / 365.25).round().astype(int)

    x_col, x_label = X_AXIS_COLS[x_axis]
    grouped = (
        df.groupby(x_col)
        .agg(
            y=("TotalDiffFromFirst", "mean"),
            std=("TotalDiffFromFirst", "std"),
            lifter_count=("Name", "nunique"),
        )
        .reset_index()
        .sort_values(x_col)
        .rename(columns={x_col: "x"})
    )
    # Single-lifter buckets have NaN std; fill with 0.
    grouped["std"] = grouped["std"].fillna(0)

    # Trendline: linear fit on points with enough lifters to be meaningful.
    trend = None
    fit = grouped[grouped["lifter_count"] >= min_lifters_for_trend]
    if len(fit) >= 2:
        x_arr = fit["x"].to_numpy(dtype=float)
        y_arr = fit["y"].to_numpy(dtype=float)
        coeffs = np.polyfit(x_arr, y_arr, deg=1)
        # R-squared: 1 - SS_res / SS_tot
        y_pred = np.polyval(coeffs, x_arr)
        ss_res = float(np.sum((y_arr - y_pred) ** 2))
        ss_tot = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        unit_map = {
            "Meet #": "meet",
            "Days": "day",
            "Weeks": "week",
            "Months": "month",
            "Years": "year",
        }
        trend = {
            "slope": float(coeffs[0]),
            "intercept": float(coeffs[1]),
            "unit": unit_map[x_axis],
            "r_squared": round(r_squared, 4),
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
        "points": points,
        "trend": trend,
        "n_lifters": int(df["Name"].nunique()),
        "n_meets": int(len(df)),
        "n_lifters_before_age_filter": n_lifters_before_age_filter,
    }
