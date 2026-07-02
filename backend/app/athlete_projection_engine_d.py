"""Athlete Projection -- Engine D (statsmodels MixedLM, advanced toggle).

  - statsmodels MixedLM per (age_division, GLP bracket, lift) cell with a
    random intercept per lifter, fixed effect for years_from_first.
  - Fitting runs at precompute time (_fit_mixedlm_cells, called from
    athlete_projection_tables.precompute_tables); the runtime path
    (mixed_effects_projection) synthesizes a virtual GlpCohortCell from
    each converged MixedLMCell and reuses Engine C's projection math.
  - Non-converged cells fall back to Engine C per lift and are reported
    in meta.engine_d_fallback_lifts.

Table state lives in athlete_projection_tables.py; Engine C in
athlete_projection_engine_c.py; the athlete_projection facade re-exports
the public surface of all three.
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd

from .data import get_cursor
from .ipf_gl_points import (
    GLP_BRACKET_LABELS,
    assign_glp_bracket,
    ipf_gl_points,
)
from .progression import age_to_category
from . import athlete_projection_tables as tables
from .athlete_projection_tables import (
    AGE_DIVISIONS,
    LIFT_COLS,
    LIFT_KEYS,
    GlpCohortCell,
    MixedLMCell,
    _load_cohort_history,
    get_km_table,
    get_mixedlm_cell,
)
from .athlete_projection_engine_c import (
    AthleteProjectionResult,
    LiftProjection,
    _aggregate_total,
    _load_lifter_history,
    _project_single_lift,
    shrinkage_projection,
)

logger = logging.getLogger(__name__)

# MixedLM fit tunables (mirror the convergence probe so production
# behaves identically to what was probed).
_MIXEDLM_MIN_LIFTERS_PER_CELL: int = 20
_MIXEDLM_MIN_MEETS_PER_CELL: int = 60
_MIXEDLM_MAXITER: int = 200
_DAYS_PER_YEAR: float = 365.25


# =============================================================================
# MixedLM cell fitting (precompute time)
# =============================================================================


def _fit_mixedlm_cells(
    cursor,
) -> tuple[dict[tuple[str, str, str], MixedLMCell], float]:
    """Fit per-cell MixedLM for Engine D.

    For each (age_division, anchor_bracket, lift) cell that clears the
    >= 20-lifter and >= 60-meet floor (after Engine C's bracket-merge
    ladder is applied), fit ``lift_kg ~ years_from_first`` with random
    intercept + slope per lifter using ``statsmodels.MixedLM``.

    Returns ``(cells_by_key, converged_pct)``. Cells that did not converge
    are still emitted with ``converged=False`` so the runtime path can
    detect the failure and per-lift fall back to Engine C's slope.
    Whole-division-too-small fallbacks are emitted with
    ``is_global_fallback=True`` and ``converged=False``.

    Algorithm mirrors ``data/probe_mixedlm_convergence.py:fit_cell_mixedlm``
    end-to-end. The probe is the contract -- any divergence here means
    the probe verdict no longer applies in production.
    """
    # Lazy imports keep module load cheap and avoid hard-pinning statsmodels
    # at import time. Failure mode classifications mirror the probe.
    import statsmodels.formula.api as smf  # noqa: PLC0415
    from statsmodels.tools.sm_exceptions import (  # noqa: PLC0415
        ConvergenceWarning,
    )

    hist = _load_cohort_history(cursor)
    if hist.empty:
        return {}, 0.0

    hist = hist.copy()
    hist["AgeDivision"] = hist["Age"].apply(age_to_category)
    hist = hist[hist["AgeDivision"].isin(AGE_DIVISIONS)]
    if hist.empty:
        return {}, 0.0

    # Per-lifter cell assignment from the latest SBD meet's GLP bracket.
    hist_sorted = hist.sort_values(["Name", "Date"])
    last_sbd = hist_sorted[hist_sorted["Event"] == "SBD"]
    last_sbd = last_sbd[last_sbd["TotalKg"].notna()]
    latest_per_name = (
        last_sbd.groupby("Name").tail(1) if not last_sbd.empty else last_sbd
    )

    name_assignment: dict[str, tuple[str, str]] = {}
    for row in latest_per_name.itertuples(index=False):
        glp = ipf_gl_points(
            total_kg=float(row.TotalKg),
            bw_kg=float(row.BodyweightKg),
            age=float(row.Age),
            sex=str(row.Sex),
        )
        bracket = assign_glp_bracket(glp)
        name_assignment[row.Name] = (str(row.AgeDivision), bracket)

    # Group lifters per (division, bracket) cell.
    partition: dict[tuple[str, str], list[str]] = {}
    for name, (division, bracket) in name_assignment.items():
        partition.setdefault((division, bracket), []).append(name)

    out: dict[tuple[str, str, str], MixedLMCell] = {}
    n_attempted = 0
    n_converged = 0
    bracket_order = GLP_BRACKET_LABELS

    for division in AGE_DIVISIONS:
        per_bracket: dict[str, list[str]] = {
            b: list(partition.get((division, b), [])) for b in bracket_order
        }
        total_in_div = sum(len(v) for v in per_bracket.values())
        if total_in_div == 0:
            continue

        # Whole-division fallback when the division is below the lifter
        # floor. Emit a single global-fallback cell per lift, not converged.
        if total_in_div < _MIXEDLM_MIN_LIFTERS_PER_CELL:
            for lift in LIFT_KEYS:
                cell = MixedLMCell(
                    division=division,
                    glp_bracket=bracket_order[0],
                    lift=lift,
                    n_lifters=total_in_div,
                    n_meets=0,
                    converged=False,
                    failure_mode="division_below_floor",
                    fixed_intercept=0.0,
                    fixed_slope_kg_per_year=0.0,
                    random_intercept_var=0.0,
                    residual_var=0.0,
                    merged_from=tuple(bracket_order),
                    is_global_fallback=True,
                )
                for label in bracket_order:
                    out[(division, label, lift)] = cell
            continue

        # Bracket-level merge ladder: low -> high, then high -> low.
        assigned = [False] * len(bracket_order)
        merged_groups: list[tuple[list[str], list[str]]] = []
        for i in range(len(bracket_order)):
            if assigned[i]:
                continue
            merged_labels = [bracket_order[i]]
            accumulated: list[str] = list(per_bracket[bracket_order[i]])

            j = i + 1
            while (
                len(accumulated) < _MIXEDLM_MIN_LIFTERS_PER_CELL
                and j < len(bracket_order)
            ):
                if assigned[j]:
                    j += 1
                    continue
                accumulated.extend(per_bracket[bracket_order[j]])
                merged_labels.append(bracket_order[j])
                assigned[j] = True
                j += 1

            k = i - 1
            while (
                len(accumulated) < _MIXEDLM_MIN_LIFTERS_PER_CELL
                and k >= 0
            ):
                if assigned[k]:
                    k -= 1
                    continue
                accumulated = list(per_bracket[bracket_order[k]]) + accumulated
                merged_labels.insert(0, bracket_order[k])
                assigned[k] = True
                k -= 1

            assigned[i] = True
            merged_groups.append((merged_labels, accumulated))

        # Fit MixedLM per merged group x lift.
        for merged_labels, lifter_names in merged_groups:
            anchor = merged_labels[0]
            merged_from = (
                tuple(merged_labels) if len(merged_labels) > 1 else ()
            )
            for lift in LIFT_KEYS:
                cell = _fit_one_mixedlm_cell(
                    hist_sorted,
                    lifter_names,
                    division,
                    anchor,
                    lift,
                    merged_from,
                    smf,
                    ConvergenceWarning,
                )
                if cell is None:
                    skip_cell = MixedLMCell(
                        division=division,
                        glp_bracket=anchor,
                        lift=lift,
                        n_lifters=len(lifter_names),
                        n_meets=0,
                        converged=False,
                        failure_mode="below_n_meets_floor",
                        fixed_intercept=0.0,
                        fixed_slope_kg_per_year=0.0,
                        random_intercept_var=0.0,
                        residual_var=0.0,
                        merged_from=merged_from,
                        is_global_fallback=False,
                    )
                    for label in merged_labels:
                        out[(division, label, lift)] = skip_cell
                    continue

                n_attempted += 1
                if cell.converged:
                    n_converged += 1
                for label in merged_labels:
                    out[(division, label, lift)] = cell

    converged_pct = (
        float(n_converged) / float(n_attempted) if n_attempted > 0 else 0.0
    )
    logger.info(
        "[athlete_projection] mixedlm fit attempted=%d converged=%d "
        "rate=%.3f",
        n_attempted, n_converged, converged_pct,
    )
    return out, converged_pct


def _fit_one_mixedlm_cell(
    hist_sorted: pd.DataFrame,
    lifter_names: list[str],
    division: str,
    anchor_bracket: str,
    lift: str,
    merged_from: tuple[str, ...],
    smf: Any,
    convergence_warning_cls: type[Warning],
) -> MixedLMCell | None:
    """Fit MixedLM on the meets of ``lifter_names`` for ``lift``.

    Returns ``None`` when the cell does not meet the n_meets floor (caller
    treats this as "skipped, not failed"). On a fit that crashes or fails
    to converge, returns a ``MixedLMCell`` with ``converged=False`` and a
    populated ``failure_mode``.
    """
    lift_col = LIFT_COLS[lift]
    rows: list[dict[str, Any]] = []
    for name in lifter_names:
        meets = hist_sorted[hist_sorted["Name"] == name].copy()
        meets = meets[meets[lift_col].notna() & (meets[lift_col] > 0)]
        if len(meets) < 2:
            continue
        dates = pd.to_datetime(meets["Date"].values)
        days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
        years = days / _DAYS_PER_YEAR
        for years_val, kg in zip(years, meets[lift_col].astype(float).values):
            rows.append({
                "lifter_id": name,
                "years_from_first": float(years_val),
                "lift_kg": float(kg),
            })

    cell_df = pd.DataFrame(rows)
    n_lifters = (
        int(cell_df["lifter_id"].nunique()) if not cell_df.empty else 0
    )
    n_meets = int(len(cell_df))
    if (
        n_lifters < _MIXEDLM_MIN_LIFTERS_PER_CELL
        or n_meets < _MIXEDLM_MIN_MEETS_PER_CELL
    ):
        return None

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", convergence_warning_cls)
            md = smf.mixedlm(
                "lift_kg ~ years_from_first",
                cell_df,
                groups=cell_df["lifter_id"],
                re_formula="~1",
            )
            result = md.fit(method="lbfgs", maxiter=_MIXEDLM_MAXITER)
    except np.linalg.LinAlgError:
        return _failed_mixedlm_cell(
            division, anchor_bracket, lift, n_lifters, n_meets,
            "singular_hessian", merged_from,
        )
    except Exception as exc:  # noqa: BLE001 -- catch-all is the point
        logger.warning(
            "[athlete_projection] mixedlm fit raised: cell=%s lift=%s "
            "exc=%r",
            (division, anchor_bracket), lift, exc,
        )
        return _failed_mixedlm_cell(
            division, anchor_bracket, lift, n_lifters, n_meets,
            "unexpected_exception", merged_from,
        )

    failure_mode: str | None = None
    if any(
        issubclass(w.category, convergence_warning_cls) for w in caught
    ):
        failure_mode = "did_not_converge"
    elif not getattr(result, "converged", True):
        failure_mode = "did_not_converge"
    else:
        cov_re = np.asarray(result.cov_re)
        if cov_re.size:
            eigs = np.linalg.eigvalsh(cov_re)
            if float(np.min(eigs)) < 1e-6:
                failure_mode = "boundary_re_cov"

    # Pull fit parameters even on failure -- statsmodels still returns
    # values, just untrustworthy. The runtime path checks ``converged``
    # and never reads the params on a failed cell.
    try:
        fixed_intercept = float(result.fe_params.get("Intercept", 0.0))
        fixed_slope = float(result.fe_params.get("years_from_first", 0.0))
    except Exception:  # noqa: BLE001
        fixed_intercept, fixed_slope = 0.0, 0.0

    # With re_formula="~1" the cov_re matrix is 1x1 (intercept variance only).
    cov_re_arr = (
        np.asarray(result.cov_re) if result.cov_re is not None else None
    )
    if cov_re_arr is not None and cov_re_arr.size >= 1:
        ri_var = float(cov_re_arr.flatten()[0])
    else:
        ri_var = 0.0

    try:
        residual_var = float(result.scale)
    except Exception:  # noqa: BLE001
        residual_var = 0.0

    return MixedLMCell(
        division=division,
        glp_bracket=anchor_bracket,
        lift=lift,
        n_lifters=n_lifters,
        n_meets=n_meets,
        converged=failure_mode is None,
        failure_mode=failure_mode,
        fixed_intercept=fixed_intercept,
        fixed_slope_kg_per_year=fixed_slope,
        random_intercept_var=ri_var,
        residual_var=residual_var,
        merged_from=merged_from,
        is_global_fallback=False,
    )


def _failed_mixedlm_cell(
    division: str,
    anchor_bracket: str,
    lift: str,
    n_lifters: int,
    n_meets: int,
    failure_mode: str,
    merged_from: tuple[str, ...],
) -> MixedLMCell:
    return MixedLMCell(
        division=division,
        glp_bracket=anchor_bracket,
        lift=lift,
        n_lifters=n_lifters,
        n_meets=n_meets,
        converged=False,
        failure_mode=failure_mode,
        fixed_intercept=0.0,
        fixed_slope_kg_per_year=0.0,
        random_intercept_var=0.0,
        residual_var=0.0,
        merged_from=merged_from,
        is_global_fallback=False,
    )


# =============================================================================
# Mixed-effects engine (Engine D runtime path)
# =============================================================================


def _mixedlm_to_virtual_cohort_cell(
    ml_cell: MixedLMCell,
) -> GlpCohortCell:
    """Synthesize a `GlpCohortCell` from a converged `MixedLMCell`.

    The runtime path treats Engine D as "Engine C with MixedLM-derived
    cohort numbers": only `slope_kg_per_day` and `residual_std` are read
    by `_project_single_lift`, so wrapping the MixedLM fixed slope and
    a per-day std in the existing dataclass lets the projection math
    stay shared. Conversion:
      slope_kg_per_day = fixed_slope_kg_per_year / 365.25
      residual_std     = sqrt(residual_var) / 365.25
    Post-P5-path-2 the model is random-intercept-only, so there is no
    per-lifter slope variance to draw from. ``residual_var`` (per-meet
    noise around the cohort line, in kg^2) is the remaining cohort
    uncertainty, mapped to a per-day equivalent so the existing Engine C
    PI formula `seg_sigma_cohort * km_mult * t_offset` stays usable.
    PIs are tighter than the v1 random-slope synthesis; that reflects
    the simpler model's narrower assumptions.
    """
    slope_per_day = ml_cell.fixed_slope_kg_per_year / _DAYS_PER_YEAR
    residual_std_kg = float(np.sqrt(max(ml_cell.residual_var, 0.0)))
    residual_std_per_day = residual_std_kg / _DAYS_PER_YEAR
    return GlpCohortCell(
        division=ml_cell.division,
        glp_bracket=ml_cell.glp_bracket,
        lift=ml_cell.lift,
        n_lifters=ml_cell.n_lifters,
        slope_kg_per_day=slope_per_day,
        residual_std=residual_std_per_day,
        merged_from=ml_cell.merged_from,
        is_global_fallback=ml_cell.is_global_fallback,
    )


def mixed_effects_projection(
    lifter_name: str,
    horizon_months: int = 12,
    n_points: int = 6,
) -> AthleteProjectionResult | None:
    """Engine D: statsmodels MixedLM per (division, bracket, lift) cell.

    For each lift, look up the MixedLM cell that matches the lifter's
    initial bracket and division. If the cell converged at precompute
    time, reproject that lift using the MixedLM fixed slope (converted
    to kg/day) as the cohort term in Engine C's existing shrinkage math
    -- random-slope std becomes the cohort uncertainty. If the cell did
    not converge (or no cell exists), keep Engine C's projection for
    that lift unchanged and record the lift in
    ``meta.engine_d_fallback_lifts``.

    ``meta.engine_d_available`` is True only when the global gate is on
    AND at least one lift used MixedLM. ``engine_d_partial`` flags the
    mixed-engine case (some lifts MixedLM, others Engine C).

    Returns None when the lifter has no projection (no meets / no age).
    """
    base = shrinkage_projection(lifter_name, horizon_months, n_points)
    if base is None:
        return None

    # Pull the lifter's initial bracket from the existing meta. Engine C
    # already resolved the (division, bracket) tuple for this lifter and
    # stored it in `lifter_bracket_meta`; we reuse it rather than recomputing
    # to keep Engine D's per-lifter dispatch identical to Engine C's.
    lifter_bracket = (base.meta or {}).get("lifter_bracket")
    initial_bracket: str | None = (
        lifter_bracket["bracket"] if lifter_bracket else None
    )

    fallback_lifts: list[str] = []
    enhanced_lifts: dict[str, LiftProjection] = dict(base.lifts)

    if initial_bracket is None or tables.get_mixedlm_cell_count() == 0:
        # No bracket resolved or no MixedLM table loaded -- everything
        # falls back to Engine C; honour Engine D semantics by listing
        # all lifts as fallbacks.
        fallback_lifts = list(LIFT_KEYS)
    else:
        cursor = get_cursor()
        lifter_df = _load_lifter_history(cursor, lifter_name)
        # lifter_df is non-None here because shrinkage_projection succeeded.

        km = get_km_table(base.age_division)
        km_multiplier = (
            km.multiplier(base.horizon_months) if km else 1.0
        )

        for lift in LIFT_KEYS:
            ml_cell = get_mixedlm_cell(
                base.age_division, initial_bracket, lift,
            )
            if ml_cell is None or not ml_cell.converged:
                fallback_lifts.append(lift)
                continue
            virtual_cell = _mixedlm_to_virtual_cohort_cell(ml_cell)
            enhanced_lifts[lift] = _project_single_lift(
                lifter_df=lifter_df,
                lift=lift,
                cohort_cell=virtual_cell,
                horizon_months=base.horizon_months,
                n_points=n_points,
                km_multiplier=km_multiplier,
            )

    all_fell_back = len(fallback_lifts) == len(LIFT_KEYS)
    partial = 0 < len(fallback_lifts) < len(LIFT_KEYS)

    # Recompute aggregate total when at least one lift used MixedLM.
    # When everything fell back, total_history / total_projected_points
    # from Engine C are still correct.
    if not all_fell_back:
        cursor = get_cursor()
        lifter_df = _load_lifter_history(cursor, lifter_name)
        if lifter_df is not None:
            total_history, total_projected = _aggregate_total(
                lifter_df, enhanced_lifts, n_points,
            )
        else:
            total_history = list(base.total_history)
            total_projected = list(base.total_projected_points)
    else:
        total_history = list(base.total_history)
        total_projected = list(base.total_projected_points)

    # Engine D is "available" for this response only when:
    #   1. The global gate is on (live precompute >= 90% convergence).
    #   2. At least one lift actually used MixedLM (not all-fallback).
    engine_d_available = (
        tables.is_engine_d_globally_available() and not all_fell_back
    )

    note: str | None = None
    if all_fell_back:
        note = (
            "All lifts fell back to Engine C: no converged MixedLM cell "
            "for this lifter's (division, bracket)."
        )
    elif partial:
        note = (
            "Some lifts fell back to Engine C because their MixedLM cell "
            "did not converge."
        )

    return AthleteProjectionResult(
        lifter_name=base.lifter_name,
        engine="mixed_effects",
        horizon_months=base.horizon_months,
        horizon_capped=base.horizon_capped,
        as_of_date=base.as_of_date,
        age_division=base.age_division,
        lifts=enhanced_lifts,
        total_history=tuple(total_history),
        total_projected_points=tuple(total_projected),
        outlier_lifts=base.outlier_lifts,
        meta={
            **base.meta,
            "engine_d_available": engine_d_available,
            "engine_d_partial": partial,
            "engine_d_fallback_lifts": tuple(fallback_lifts),
            "engine_d_note": note,
        },
    )
