"""Athlete Projection -- Engine C (Bayesian shrinkage, shipping default).

  - Personal slope per lift via Huber-robust regression (statsmodels RLM).
  - Cohort slope per lift from the precomputed (age division x GLP bracket)
    cells in athlete_projection_tables.py.
  - Combined slope: w_p * slope_personal + (1 - w_p) * slope_cohort
    with w_p = n / (n + 5). n counts lifts CONTESTED for that lift, not meets.
  - Current level per lift: max of last 3 contested totals (median of last 2
    if n<3).
  - Prediction interval: PI(t) = est +/- 1.96 * sqrt(sigma_resid^2 +
    var_params(t)), inflated by a Kaplan-Meier dropout multiplier on the
    cohort term.

Table state lives in athlete_projection_tables.py; Engine D in
athlete_projection_engine_d.py; the athlete_projection facade re-exports
the public surface of all three.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .data import get_cursor
from .ipf_gl_points import (
    GLP_BRACKET_LABELS,
    assign_glp_bracket,
    ipf_gl_points,
)
from .constants import (
    DAYS_PER_MONTH,
    HORIZON_MONTHS_HARD_CAP,
    HORIZON_MONTHS_SMALL_N_CAP,
    HORIZON_MONTHS_WARN,
    OUTLIER_SIGMA,
    SHRINKAGE_K,
    SMALL_N_THRESHOLD,
    Z_95,
)
from .progression import age_to_category
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION
from . import athlete_projection_tables as tables
from .athlete_projection_tables import (
    AGE_DIVISIONS,
    LIFT_COLS,
    LIFT_KEYS,
    GlpCohortCell,
    _robust_slope,
    get_cohort_cell,
    get_km_table,
)


# =============================================================================
# Result DTOs (frozen; immutable by default)
# =============================================================================


@dataclass(frozen=True)
class LiftProjection:
    """Projection result for a single lift (squat / bench / deadlift)."""

    lift: str
    n_meets: int                        # lift-specific meets contesting this lift
    current_level: float | None         # kg; max of last 3 (median of last 2 if n<3)
    slope_personal_kg_per_day: float | None
    slope_cohort_kg_per_day: float | None
    slope_combined_kg_per_day: float | None
    w_personal: float                   # n / (n + k)
    sigma_resid: float                  # kg; personal residual std (cohort if missing)
    s_xx: float | None                  # fitting var denom; None if <2 meets
    t_mean_days: float | None
    last_meet_day: float | None         # days from first meet for last contest
    projected_points: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    # Actual historical meets that contested this lift. Each entry is
    # {"date": "YYYY-MM-DD", "days_from_first": float, "kg": float}. Origin
    # is the lifter's first meet that contested this lift, matching the
    # days_from_first scale used by projected_points.
    history: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AthleteProjectionResult:
    """Top-level projection response envelope returned by the two engines."""

    lifter_name: str
    engine: str
    horizon_months: int
    horizon_capped: bool                # True if horizon was clamped server-side
    as_of_date: str                     # ISO date of latest meet
    age_division: str
    lifts: dict[str, LiftProjection]    # key: "squat" | "bench" | "deadlift"
    total_history: tuple[dict[str, Any], ...]   # actual SBD totals for plotting
    total_projected_points: tuple[dict[str, Any], ...]
    outlier_lifts: tuple[str, ...]      # lifts where last meet > 2.5 sigma below fit
    meta: dict[str, Any]


# =============================================================================
# Shrinkage engine (Engine C)
# =============================================================================


def shrinkage_projection(
    lifter_name: str,
    horizon_months: int = 12,
    n_points: int = 6,
) -> AthleteProjectionResult | None:
    """Engine C: Bayesian shrinkage with Huber personal + GLP-bracket cohort.

    Returns None if the lifter has no meets or no age data to assign a cohort.

    Two-pass bracket transition: pass 1 uses the lifter's starting GLP
    bracket's cohort slope; if the projected total crosses a bracket edge
    during the horizon, pass 2 re-projects with per-segment cohort cells.
    """
    cursor = get_cursor()
    lifter_df = _load_lifter_history(cursor, lifter_name)
    if lifter_df is None or lifter_df.empty:
        return None

    age_division = _assign_division(lifter_df)
    if age_division is None:
        return None

    n_total_meets = int(lifter_df["Name"].count())
    effective_horizon, capped = _clamp_horizon(horizon_months, n_total_meets)

    glp, initial_bracket, bw_used, age_used, sex_used = _compute_lifter_glp(lifter_df)

    km = get_km_table(age_division)
    km_multiplier = km.multiplier(effective_horizon) if km else 1.0

    # Pass 1: use the initial bracket for all n_points.
    pass1_projs: dict[str, LiftProjection] = {}
    for lift in LIFT_KEYS:
        cell = get_cohort_cell(age_division, initial_bracket, lift)
        pass1_projs[lift] = _project_single_lift(
            lifter_df=lifter_df,
            lift=lift,
            cohort_cell=cell,
            horizon_months=effective_horizon,
            n_points=n_points,
            km_multiplier=km_multiplier,
        )

    # Determine bracket per horizon point from pass-1 totals.
    brackets_per_point = _compute_brackets_per_point(
        pass1_projs, bw_used, age_used, sex_used, initial_bracket, n_points,
    )

    # Pass 2 only if any point's bracket differs from the initial.
    if all(b == initial_bracket for b in brackets_per_point):
        lift_results = pass1_projs
    else:
        lift_results = {}
        for lift in LIFT_KEYS:
            cells_per_point = [
                get_cohort_cell(age_division, b, lift) for b in brackets_per_point
            ]
            lift_results[lift] = _project_single_lift(
                lifter_df=lifter_df,
                lift=lift,
                cohort_cell=get_cohort_cell(age_division, initial_bracket, lift),
                horizon_months=effective_horizon,
                n_points=n_points,
                km_multiplier=km_multiplier,
                cohort_cells_per_point=cells_per_point,
            )

    outlier_lifts = [
        lift for lift in LIFT_KEYS
        if _is_outlier_latest(lifter_df, lift, lift_results[lift])
    ]

    total_history, total_projected = _aggregate_total(
        lifter_df, lift_results, n_points,
    )

    # Lifter-bracket meta: pull from the squat cell as representative (all
    # three lifts share the same bracket for the initial cell).
    primary_cell = get_cohort_cell(age_division, initial_bracket, "squat")
    lifter_bracket_meta: dict[str, Any] | None = None
    if primary_cell is not None:
        lifter_bracket_meta = {
            "bracket": initial_bracket,
            "n_cell": primary_cell.n_lifters,
            "merged_from": list(primary_cell.merged_from),
            "is_global_fallback": primary_cell.is_global_fallback,
            "glp_score": round(glp, 1) if glp is not None else None,
        }

    bracket_transitions = sum(
        1 for i in range(1, len(brackets_per_point))
        if brackets_per_point[i] != brackets_per_point[i - 1]
    )

    return AthleteProjectionResult(
        lifter_name=lifter_name,
        engine="shrinkage",
        horizon_months=effective_horizon,
        horizon_capped=capped,
        as_of_date=str(lifter_df["Date"].max())[:10],
        age_division=age_division,
        lifts=lift_results,
        total_history=tuple(total_history),
        total_projected_points=tuple(total_projected),
        outlier_lifts=tuple(outlier_lifts),
        meta={
            "lifter_bracket": lifter_bracket_meta,
            "km_multiplier": km_multiplier,
            "km_sample_size": km.sample_size if km else 0,
            "precomputed": tables.is_precomputed(),
            "small_n_warning": n_total_meets < SMALL_N_THRESHOLD,
            "long_horizon_warning": horizon_months > HORIZON_MONTHS_WARN,
            "brackets_per_point": list(brackets_per_point),
            "bracket_transitions": bracket_transitions,
        },
    )


def _compute_lifter_glp(
    lifter_df: pd.DataFrame,
) -> tuple[float | None, str, float | None, float | None, str | None]:
    """From the most recent SBD meet with non-null total/BW/Age/Sex, compute
    GLP and the assigned bracket. Falls back to any meet if no SBD match.

    Returns (glp, bracket_label, bw_used, age_used, sex_used).
    """
    sbd = lifter_df[
        (lifter_df["Event"] == "SBD")
        & lifter_df["TotalKg"].notna()
        & lifter_df["BodyweightKg"].notna()
        & lifter_df["Age"].notna()
        & lifter_df["Sex"].notna()
    ]
    source = sbd if not sbd.empty else lifter_df[lifter_df["TotalKg"].notna()]
    if source.empty:
        return None, GLP_BRACKET_LABELS[0], None, None, None

    row = source.iloc[-1]
    total = float(row["TotalKg"]) if pd.notna(row["TotalKg"]) else None
    bw = float(row["BodyweightKg"]) if pd.notna(row["BodyweightKg"]) else None
    age = float(row["Age"]) if pd.notna(row["Age"]) else None
    sex = str(row["Sex"]) if pd.notna(row["Sex"]) else None
    glp = ipf_gl_points(total, bw, age, sex)
    return glp, assign_glp_bracket(glp), bw, age, sex


def _compute_brackets_per_point(
    pass1_projs: dict[str, "LiftProjection"],
    bw: float | None,
    age: float | None,
    sex: str | None,
    initial_bracket: str,
    n_points: int,
) -> list[str]:
    """Per horizon point, assign a bracket from the pass-1 projected total.

    If any required IPF-GL input is missing, keep the initial bracket for
    every point (no transitions attempted).
    """
    if bw is None or age is None or sex is None:
        return [initial_bracket] * n_points

    squat_pts = pass1_projs["squat"].projected_points
    bench_pts = pass1_projs["bench"].projected_points
    dead_pts = pass1_projs["deadlift"].projected_points
    if not (len(squat_pts) == len(bench_pts) == len(dead_pts) == n_points):
        return [initial_bracket] * n_points

    out: list[str] = []
    for i in range(n_points):
        total_i = (
            float(squat_pts[i]["projected_kg"])
            + float(bench_pts[i]["projected_kg"])
            + float(dead_pts[i]["projected_kg"])
        )
        glp_i = ipf_gl_points(total_i, bw, age, sex)
        out.append(assign_glp_bracket(glp_i))
    return out


def _load_lifter_history(cursor, name: str) -> pd.DataFrame | None:
    sql = f"""
        SELECT Name, Sex, Age, BodyweightKg, Date, Event, Division,
               Best3SquatKg, Best3BenchKg, Best3DeadliftKg, TotalKg,
               CanonicalWeightClass, Equipment
        FROM openipf
        WHERE Name = ?
          AND Country = '{DEFAULT_COUNTRY}'
          AND ParentFederation = '{DEFAULT_PARENT_FEDERATION}'
        ORDER BY Date
    """
    df = cursor.execute(sql, [name]).df()
    if df.empty:
        return None
    df["Date"] = pd.to_datetime(df["Date"])
    return df


_DIVISION_TEXT_MAP: dict[str, str] = {
    "Open": "Open",
    "Sub-Junior": "Sub-Jr",
    "Sub-Juniors": "Sub-Jr",
    "SJ": "Sub-Jr",
    "Junior": "Jr",
    "Juniors": "Jr",
    "Jr": "Jr",
    "Master 1": "M1",
    "Masters 1": "M1",
    "M1": "M1",
    "Master 2": "M2",
    "Masters 2": "M2",
    "M2": "M2",
    "Master 3": "M3",
    "Masters 3": "M3",
    "M3": "M3",
    "Master 4": "M4",
    "Masters 4": "M4",
    "M4": "M4",
}


def _assign_division(lifter_df: pd.DataFrame) -> str | None:
    """Derive the lifter's age division.

    Priority:
      1. Age column on the most recent meet that has a non-null Age.
      2. Free-text Division column on the most recent meet (CPU canonical
         labels or common OpenIPF spellings mapped to AGE_DIVISIONS keys).
      3. Fall back to 'Open' so a lifter with no Age and a missing/exotic
         Division still gets a projection (rather than a found=false stub).
    """
    age_rows = lifter_df[lifter_df["Age"].notna()]
    if not age_rows.empty:
        last_age = float(age_rows.iloc[-1]["Age"])
        div = age_to_category(last_age)
        if isinstance(div, str) and div in AGE_DIVISIONS:
            return div

    for raw in reversed(lifter_df["Division"].tolist() if "Division" in lifter_df.columns else []):
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        mapped = _DIVISION_TEXT_MAP.get(str(raw).strip())
        if mapped in AGE_DIVISIONS:
            return mapped

    return "Open"


def _clamp_horizon(horizon: int, n_meets: int) -> tuple[int, bool]:
    """Apply hard + small-N caps. Returns (effective, was_capped)."""
    h = max(1, int(horizon))
    cap = HORIZON_MONTHS_HARD_CAP
    if n_meets < SMALL_N_THRESHOLD:
        cap = HORIZON_MONTHS_SMALL_N_CAP
    if h > cap:
        return cap, True
    return h, False


def compute_current_level(values: list[float]) -> float | None:
    """Current lift level: max of last 3 (median of last 2 if n<3, single if n==1).

    Level is NOT shrunk -- we want the lifter's actual current capability.
    """
    valid = [float(v) for v in values if v is not None and not pd.isna(v)]
    if not valid:
        return None
    if len(valid) >= 3:
        return float(max(valid[-3:]))
    if len(valid) == 2:
        return float(np.median(valid[-2:]))
    return float(valid[-1])


def _project_single_lift(
    lifter_df: pd.DataFrame,
    lift: str,
    cohort_cell: GlpCohortCell | None,
    horizon_months: int,
    n_points: int,
    km_multiplier: float,
    cohort_cells_per_point: list[GlpCohortCell | None] | None = None,
) -> LiftProjection:
    """Project one lift across n_points using a cohort cell for the cohort slope.

    If cohort_cells_per_point is provided (length n_points), each segment's
    cohort slope comes from that list, supporting bracket transitions. The
    personal slope stays constant across the horizon (shrinkage is only on
    the combined-slope contribution each segment).

    PI variance at point t:
      var_personal_at_t = sigma_personal^2 * (1 + 1/n + (t - t_mean)^2 / S_xx)
      var_cohort_slope(t) = (cohort_slope_std * km_mult * t_offset)^2
      var_total = w_p^2 * var_personal_at_t + (1 - w_p)^2 * var_cohort_slope(t)
      pi_half = z95 * sqrt(var_total)
    """
    col = LIFT_COLS[lift]
    sub = lifter_df[lifter_df[col].notna()].copy()
    n_meets = int(len(sub))

    if n_meets == 0:
        return LiftProjection(
            lift=lift, n_meets=0, current_level=None,
            slope_personal_kg_per_day=None, slope_cohort_kg_per_day=None,
            slope_combined_kg_per_day=None,
            w_personal=0.0, sigma_resid=0.0, s_xx=None,
            t_mean_days=None, last_meet_day=None,
            projected_points=tuple(),
        )

    values = sub[col].astype(float).tolist()
    current_level = compute_current_level(values)

    dates = pd.to_datetime(sub["Date"].values)
    first_date = dates[0]
    days = ((dates - first_date) / np.timedelta64(1, "D")).astype(float)
    last_meet_day = float(days[-1])

    # Build the per-lift history series. Origin is this lift's first meet,
    # matching the days_from_first scale used by projected_points so the
    # frontend can plot both on the same x-axis without further offset.
    history_rows: list[dict[str, Any]] = []
    for idx in range(len(sub)):
        history_rows.append({
            "date": str(sub["Date"].iloc[idx])[:10],
            "days_from_first": round(float(days[idx]), 1),
            "kg": round(float(values[idx]), 1),
        })

    # Personal slope (Huber, with polyfit fallback).
    slope_personal: float | None = None
    sigma_personal: float | None = None
    s_xx: float | None = None
    t_mean_days: float | None = None

    if n_meets >= 2 and len(np.unique(days)) >= 2:
        fit = _robust_slope(days, np.asarray(values))
        if fit is not None:
            slope_personal, _intercept, sigma_personal = fit
        t_mean_days = float(np.mean(days))
        s_xx = float(np.sum((days - t_mean_days) ** 2))

    def _cell_slope(cell: GlpCohortCell | None) -> tuple[float | None, float]:
        if cell is None:
            return None, 0.0
        return float(cell.slope_kg_per_day), float(cell.residual_std)

    initial_slope_cohort, initial_sigma_cohort = _cell_slope(cohort_cell)

    # Combined slope (for the reported top-level metric; segments may differ).
    w_personal = n_meets / (n_meets + SHRINKAGE_K)
    slope_combined: float | None = None
    if slope_personal is not None and initial_slope_cohort is not None:
        slope_combined = (
            w_personal * slope_personal
            + (1 - w_personal) * initial_slope_cohort
        )
    elif slope_personal is not None:
        slope_combined = slope_personal
    elif initial_slope_cohort is not None:
        slope_combined = initial_slope_cohort
        w_personal = 0.0  # no personal data -> pure cohort

    # Instantaneous kg noise. Prefer the lifter's own residual std.
    if sigma_personal is not None and sigma_personal > 0:
        sigma_resid = float(sigma_personal)
    else:
        # Rough kg fallback: scale the cohort slope's per-day std by half
        # the horizon to produce a plausible kg magnitude for PI display.
        sigma_resid = float(
            initial_sigma_cohort * km_multiplier
            * (horizon_months * DAYS_PER_MONTH) * 0.5
        )

    # Project forward segment by segment.
    projected: list[dict[str, Any]] = []
    if current_level is not None and (
        slope_personal is not None or initial_slope_cohort is not None
    ):
        step_days = (horizon_months * DAYS_PER_MONTH) / max(1, n_points)
        running_level = float(current_level)
        running_day = last_meet_day
        for i in range(1, n_points + 1):
            next_day = last_meet_day + step_days * i
            segment_days = next_day - running_day

            # Pick segment cohort cell.
            if cohort_cells_per_point is not None and (i - 1) < len(cohort_cells_per_point):
                seg_cell = cohort_cells_per_point[i - 1]
            else:
                seg_cell = cohort_cell
            seg_slope_cohort, seg_sigma_cohort = _cell_slope(seg_cell)

            # Segment combined slope with slope-only shrinkage.
            if slope_personal is not None and seg_slope_cohort is not None:
                seg_slope = (
                    w_personal * slope_personal
                    + (1 - w_personal) * seg_slope_cohort
                )
            elif slope_personal is not None:
                seg_slope = slope_personal
            elif seg_slope_cohort is not None:
                seg_slope = seg_slope_cohort
            else:
                seg_slope = 0.0

            running_level = running_level + seg_slope * segment_days

            # PI variance at this horizon point.
            t_offset = next_day - last_meet_day
            if s_xx is not None and s_xx > 0 and sigma_personal is not None and n_meets >= 2:
                var_personal_at_t = sigma_personal ** 2 * (
                    1.0 + 1.0 / n_meets
                    + (next_day - (t_mean_days or 0.0)) ** 2 / s_xx
                )
            else:
                var_personal_at_t = 0.0
            var_cohort_at_t = (
                seg_sigma_cohort * km_multiplier * t_offset
            ) ** 2

            w2_personal = w_personal ** 2
            w2_cohort = (1.0 - w_personal) ** 2
            if slope_personal is None:
                w2_cohort = 1.0
                w2_personal = 0.0
            if seg_slope_cohort is None:
                w2_cohort = 0.0
                w2_personal = 1.0 if slope_personal is not None else 0.0
            var_total = (
                w2_personal * var_personal_at_t
                + w2_cohort * var_cohort_at_t
            )
            if w2_personal == 0 and w2_cohort == 0:
                # No data whatsoever, show a neutral band from sigma_resid.
                var_total = sigma_resid ** 2
            pi_half = Z_95 * float(np.sqrt(max(var_total, 0.0)))

            projected.append({
                "days_from_first": round(next_day, 1),
                "months_from_last": round(
                    (next_day - last_meet_day) / DAYS_PER_MONTH, 2,
                ),
                "projected_kg": round(running_level, 1),
                "lower_kg": round(running_level - pi_half, 1),
                "upper_kg": round(running_level + pi_half, 1),
            })
            running_day = next_day

    return LiftProjection(
        lift=lift,
        n_meets=n_meets,
        current_level=round(current_level, 1) if current_level is not None else None,
        slope_personal_kg_per_day=(
            round(slope_personal, 5) if slope_personal is not None else None
        ),
        slope_cohort_kg_per_day=(
            round(initial_slope_cohort, 5) if initial_slope_cohort is not None else None
        ),
        slope_combined_kg_per_day=(
            round(slope_combined, 5) if slope_combined is not None else None
        ),
        w_personal=round(w_personal, 3),
        sigma_resid=round(sigma_resid, 2),
        s_xx=s_xx,
        t_mean_days=t_mean_days,
        last_meet_day=last_meet_day,
        projected_points=tuple(projected),
        history=tuple(history_rows),
    )


def _is_outlier_latest(
    lifter_df: pd.DataFrame,
    lift: str,
    proj: LiftProjection,
) -> bool:
    """True if the most recent lift-specific meet sits > 2.5 sigma below the fit."""
    col = LIFT_COLS[lift]
    sub = lifter_df[lifter_df[col].notna()]
    if len(sub) < 3 or proj.slope_personal_kg_per_day is None or proj.sigma_resid <= 0:
        return False
    last_val = float(sub[col].iloc[-1])
    # Expected at last_meet_day: slope_personal * last_meet_day + intercept.
    # We don't store intercept separately; reconstruct from the fit:
    dates = pd.to_datetime(sub["Date"].values)
    days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
    fit = _robust_slope(days, sub[col].astype(float).to_numpy())
    if fit is None:
        return False
    slope, intercept, _resid_std = fit
    expected = slope * days[-1] + intercept
    return (expected - last_val) > OUTLIER_SIGMA * proj.sigma_resid


def _aggregate_total(
    lifter_df: pd.DataFrame,
    lifts: dict[str, LiftProjection],
    n_points: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sum per-lift projections into total. History keeps actual TotalKg.

    Per-lift projection points share x-axis (months_from_last). Sum the
    three per-lift projections point-by-point where all three are present.
    """
    sbd = lifter_df[lifter_df["Event"] == "SBD"].copy()
    history: list[dict[str, Any]] = []
    if not sbd.empty:
        first_date = sbd["Date"].iloc[0]
        for _, row in sbd.iterrows():
            total = row.get("TotalKg")
            if total is None or pd.isna(total):
                continue
            td = row["Date"] - first_date
            days = float(td.total_seconds() / 86400.0)
            history.append({
                "date": str(row["Date"])[:10],
                "days_from_first": round(days, 1),
                "total_kg": float(total),
            })

    per_lift_points = [lifts[k].projected_points for k in LIFT_KEYS]
    if not all(len(pts) == n_points for pts in per_lift_points):
        return history, []

    total_points: list[dict[str, Any]] = []
    for i in range(n_points):
        pt_squat = per_lift_points[0][i]
        pt_bench = per_lift_points[1][i]
        pt_dead = per_lift_points[2][i]
        projected = float(
            pt_squat["projected_kg"] + pt_bench["projected_kg"] + pt_dead["projected_kg"]
        )
        # Sum variances in quadrature for the combined PI half-width.
        half_sum_sq = (
            ((pt_squat["upper_kg"] - pt_squat["projected_kg"]) / Z_95) ** 2
            + ((pt_bench["upper_kg"] - pt_bench["projected_kg"]) / Z_95) ** 2
            + ((pt_dead["upper_kg"] - pt_dead["projected_kg"]) / Z_95) ** 2
        )
        combined_half = Z_95 * float(np.sqrt(half_sum_sq))
        total_points.append({
            "days_from_first": pt_squat["days_from_first"],
            "months_from_last": pt_squat["months_from_last"],
            "projected_kg": round(projected, 1),
            "lower_kg": round(projected - combined_half, 1),
            "upper_kg": round(projected + combined_half, 1),
        })
    return history, total_points


# =============================================================================
# Response serialization
# =============================================================================


def to_response_dict(result: AthleteProjectionResult) -> dict[str, Any]:
    """Serialize AthleteProjectionResult to a plain dict for JSON encoding."""
    return {
        "lifter_name": result.lifter_name,
        "engine": result.engine,
        "horizon_months": result.horizon_months,
        "horizon_capped": result.horizon_capped,
        "as_of_date": result.as_of_date,
        "age_division": result.age_division,
        "lifts": {
            key: {
                "lift": lp.lift,
                "n_meets": lp.n_meets,
                "current_level": lp.current_level,
                "slope_personal_kg_per_day": lp.slope_personal_kg_per_day,
                "slope_cohort_kg_per_day": lp.slope_cohort_kg_per_day,
                "slope_combined_kg_per_day": lp.slope_combined_kg_per_day,
                "slope_combined_kg_per_month": (
                    round(lp.slope_combined_kg_per_day * DAYS_PER_MONTH, 2)
                    if lp.slope_combined_kg_per_day is not None else None
                ),
                "w_personal": lp.w_personal,
                "sigma_resid_kg": lp.sigma_resid,
                "last_meet_day": lp.last_meet_day,
                "projected_points": list(lp.projected_points),
                "history": list(lp.history),
            }
            for key, lp in result.lifts.items()
        },
        "total_history": list(result.total_history),
        "total_projected_points": list(result.total_projected_points),
        "outlier_lifts": list(result.outlier_lifts),
        "meta": result.meta,
    }
