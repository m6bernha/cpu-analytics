"""Rankings: active-lifter leaderboard + GLP percentile distribution.

Phase 0 of the stateless social layer (docs/adr/0002-social-layer-stateless.md).

Two scope rules apply to everything in this module and are deliberate:

* **Raw SBD only.** IPF GL Points coefficients are defined for Raw Classic
  SBD (see `ipf_gl_points.py`); equipped Goodlift values use different
  coefficients, so mixing them into one percentile curve would compare
  incomparable numbers. The ADR listed equipment as a filter, but shipping
  it would make the headline metric wrong, so v1 is Raw SBD only.
* **Active = last 24 months.** The window ends at the newest in-scope meet
  date in the parquet, not at wall-clock today, so a stalled data pipeline
  does not slowly empty the board. `window_start`/`window_end` ship in
  every response so the UI can state the window it is showing.

Percentiles are computed over the active cohort per sex, so "top 5%" reads
as "top 5% of Canadian IPF lifters who competed in the last 24 months".
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .data import get_cursor
from .progression import CPU_DIVISION_ALIASES
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION

# 24 months of "active". Kept as days so the SQL stays integer arithmetic.
ACTIVE_WINDOW_DAYS = 730

# Ranking metrics -> (column, label). Whitelist: the column is interpolated
# into the ORDER BY, so it must never come from user input directly.
RANKING_METRICS: dict[str, tuple[str, str]] = {
    "glp": ("Goodlift", "IPF GL Points"),
    "total": ("TotalKg", "Total (kg)"),
}

MAX_LIMIT = 200
DEFAULT_LIMIT = 50

# Percentile curve resolution: GLP value at each whole percentile 0..100.
# 101 floats per sex is a trivial payload and lets the client resolve any
# lifter's percentile by binary search without a round trip.
_QUANTILE_LIST_SQL = "[" + ",".join(f"{i / 100:.2f}" for i in range(101)) + "]"

# Base scope shared by both endpoints: Canadian IPF Raw full-power results
# that actually carry the numbers we rank on.
_BASE_CLAUSES = [
    "Country = ?",
    "ParentFederation = ?",
    "Event = 'SBD'",
    "Equipment = 'Raw'",
    "TotalKg IS NOT NULL",
    "Goodlift IS NOT NULL",
    "Date IS NOT NULL",
]


def _base_params() -> list[Any]:
    return [DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION]


def _window_bounds(cursor: Any) -> tuple[str | None, str | None]:
    """(window_start, window_end) as ISO dates, anchored to the newest meet.

    Returns (None, None) when the scope has no rows at all, which callers
    turn into an empty response rather than a crash.
    """
    row = cursor.execute(
        f"SELECT MAX(Date) FROM openipf WHERE {' AND '.join(_BASE_CLAUSES)}",
        _base_params(),
    ).fetchone()
    if not row or row[0] is None:
        return None, None
    end = str(row[0])[:10]
    try:
        start = (date.fromisoformat(end) - timedelta(days=ACTIVE_WINDOW_DAYS)).isoformat()
    except ValueError:
        return None, None
    return start, end


def _filter_clauses(
    sex: str | None,
    weight_class: str | None,
    division: str | None,
) -> tuple[list[str], list[Any]]:
    """Optional user filters layered on top of the base scope."""
    clauses: list[str] = []
    params: list[Any] = []

    if sex and sex != "All":
        clauses.append("Sex = ?")
        params.append(sex)

    if weight_class and weight_class not in ("All", "Overall"):
        clauses.append("CanonicalWeightClass = ?")
        params.append(weight_class)

    # Division is free text in OpenIPF; reuse the canonical alias table so
    # "Master 1" also matches "Masters 1" / "M1" / "Masters 40-49".
    if division and division != "All":
        aliases = CPU_DIVISION_ALIASES.get(division)
        if aliases:
            placeholders = ",".join("?" * len(aliases))
            clauses.append(f"Division IN ({placeholders})")
            params.extend(aliases)
        else:
            clauses.append("Division = ?")
            params.append(division)

    return clauses, params


def get_percentile_curves() -> dict[str, Any]:
    """Per-sex GLP percentile curve over the active cohort.

    Response shape:
        {window_start, window_end, curves: {M: {n, glp: [101 floats]}, ...}}

    `glp[p]` is the GLP score at the p-th percentile, ascending. A lifter
    scoring >= glp[95] is in the top 5%.
    """
    cursor = get_cursor()
    start, end = _window_bounds(cursor)
    if start is None:
        return {"window_start": None, "window_end": None, "curves": {}}

    sql = f"""
        WITH scoped AS (
            SELECT Name, Sex, Goodlift
            FROM openipf
            WHERE {' AND '.join(_BASE_CLAUSES)} AND Date >= CAST(? AS DATE)
        ),
        best AS (
            SELECT Name, Sex, MAX(Goodlift) AS best_glp
            FROM scoped
            GROUP BY Name, Sex
        )
        SELECT
            Sex,
            COUNT(*) AS n,
            quantile_cont(best_glp, {_QUANTILE_LIST_SQL}) AS curve
        FROM best
        GROUP BY Sex
    """
    rows = cursor.execute(sql, [*_base_params(), start]).fetchall()

    curves: dict[str, Any] = {}
    for sex, n, curve in rows:
        curves[str(sex)] = {
            "n": int(n),
            "glp": [round(float(v), 2) for v in curve],
        }
    return {"window_start": start, "window_end": end, "curves": curves}


def compute_leaderboard(
    sex: str | None = None,
    weight_class: str | None = None,
    division: str | None = None,
    metric: str = "glp",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Ranked active lifters, one row per lifter at their best meet.

    "Best" is resolved by the ranking metric, so every column in a row
    (total, GLP, class, date) comes from the same meet rather than being
    independent maxima across a career.
    """
    if metric not in RANKING_METRICS:
        metric = "glp"
    metric_col, metric_label = RANKING_METRICS[metric]
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))

    cursor = get_cursor()
    start, end = _window_bounds(cursor)
    empty = {
        "rows": [],
        "n_total": 0,
        "limit": limit,
        "offset": offset,
        "metric": metric,
        "metric_label": metric_label,
        "window_start": start,
        "window_end": end,
    }
    if start is None:
        return empty

    extra_clauses, extra_params = _filter_clauses(sex, weight_class, division)
    where_sql = " AND ".join([*_BASE_CLAUSES, "Date >= CAST(? AS DATE)", *extra_clauses])
    params = [*_base_params(), start, *extra_params]

    # metric_col is whitelisted above, never raw user input.
    sql = f"""
        WITH scoped AS (
            SELECT
                Name, Sex, CanonicalWeightClass, Division, BodyweightKg,
                TotalKg, Goodlift, Date, MeetName,
                ROW_NUMBER() OVER (
                    PARTITION BY Name
                    ORDER BY {metric_col} DESC, Date DESC
                ) AS rn,
                -- Meets inside the active window, NOT career total. Named
                -- accordingly in the response so the UI cannot imply
                -- "career meets" from a windowed count.
                COUNT(*) OVER (PARTITION BY Name) AS n_meets_in_window
            FROM openipf
            WHERE {where_sql}
        ),
        best AS (
            SELECT * FROM scoped WHERE rn = 1
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (ORDER BY {metric_col} DESC, Name) AS rank,
                COUNT(*) OVER () AS n_total
            FROM best
        )
        SELECT
            rank, n_total, Name, Sex, CanonicalWeightClass, Division,
            BodyweightKg, TotalKg, Goodlift, Date, MeetName, n_meets_in_window
        FROM ranked
        ORDER BY rank
        LIMIT ? OFFSET ?
    """
    rows = cursor.execute(sql, [*params, limit, offset]).fetchall()
    if not rows:
        return empty

    out = []
    for r in rows:
        (
            rank, _n_total, name, row_sex, wclass, div,
            bw, total, glp, meet_date, meet_name, n_meets_in_window,
        ) = r
        out.append({
            "rank": int(rank),
            "name": name,
            "sex": row_sex,
            "weight_class": wclass,
            "division": div,
            "bodyweight_kg": float(bw) if bw is not None else None,
            "total_kg": float(total) if total is not None else None,
            "glp": round(float(glp), 2) if glp is not None else None,
            "date": str(meet_date)[:10] if meet_date is not None else None,
            "meet_name": meet_name,
            "n_meets_in_window": int(n_meets_in_window),
        })

    return {
        "rows": out,
        "n_total": int(rows[0][1]),
        "limit": limit,
        "offset": offset,
        "metric": metric,
        "metric_label": metric_label,
        "window_start": start,
        "window_end": end,
    }
