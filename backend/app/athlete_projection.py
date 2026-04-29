"""Athlete Projection -- per-lift Bayesian shrinkage (Engine C) and
mixed-effects (Engine D) projection engines.

Engine C (shipping default):
  - Personal slope per lift via Huber-robust regression (statsmodels RLM).
  - Cohort slope per lift per age division via level-conditioned exp-decay fit,
    slope(level) = a * exp(-b * level), LOESS fallback, global-mean fallback.
  - Combined slope: w_p * slope_personal + (1 - w_p) * slope_cohort(current_level)
    with w_p = n / (n + 5). n counts lifts CONTESTED for that lift, not meets.
  - Current level per lift: max of last 3 contested totals (median of last 2 if n<3).
  - Prediction interval: PI(t) = est +/- 1.96 * sqrt(sigma_resid^2 + var_params(t)),
    inflated by a Kaplan-Meier dropout multiplier on the cohort term.

Engine D (advanced toggle):
  - statsmodels MixedLM per lift with random intercept + random slope per lifter,
    fixed effects for age division + current level bracket.
  - Posterior predictive interval from MixedLM.

Cohort tables and K-M multipliers are precomputed in the FastAPI lifespan
and cached as module-level state. No per-request cohort fitting.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

from .data import get_cursor
from .ipf_gl_points import (
    GLP_BRACKET_LABELS,
    assign_glp_bracket,
    ipf_gl_points,
)
from .progression import age_to_category
from .scope import DEFAULT_COUNTRY, DEFAULT_PARENT_FEDERATION

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

Lift = Literal["squat", "bench", "deadlift"]
Engine = Literal["shrinkage", "mixed_effects"]

LIFT_COLS: dict[str, str] = {
    "squat":    "Best3SquatKg",
    "bench":    "Best3BenchKg",
    "deadlift": "Best3DeadliftKg",
}
LIFT_KEYS: tuple[str, ...] = ("squat", "bench", "deadlift")

AGE_DIVISIONS: tuple[str, ...] = ("Sub-Jr", "Jr", "Open", "M1", "M2", "M3", "M4")

SHRINKAGE_K: int = 5                  # w_p = n / (n + SHRINKAGE_K)
CURRENT_LEVEL_WINDOW: int = 3         # max of last 3 lift-specific totals
KM_DROPOUT_MONTHS: int = 18           # last meet > this many months -> censored dropout
Z_95: float = 1.96                    # normal critical value for 95% PI

HORIZON_MONTHS_HARD_CAP: int = 18
HORIZON_MONTHS_SMALL_N_CAP: int = 6
HORIZON_MONTHS_WARN: int = 12
SMALL_N_THRESHOLD: int = 5

OUTLIER_SIGMA: float = 2.5            # latest meet > this many sigma below fit -> flag

DAYS_PER_MONTH: float = 30.44
MIN_COHORT_CELL_SIZE: int = 20        # (division x bracket x lift) cell floor; below, merge


# =============================================================================
# Data classes (frozen DTOs; immutable by default)
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
# Cohort + K-M precompute tables (populated at app startup)
# =============================================================================


@dataclass(frozen=True)
class GlpCohortCell:
    """Cohort slope for one (age_division, GLP bracket, lift) cell.

    Fit: mean of per-lifter Huber slopes in the cell. Merge-fallback may
    combine adjacent GLP brackets within the same division to reach
    MIN_COHORT_CELL_SIZE. If the entire division has fewer than the
    minimum, a division-global fallback is applied and is_global_fallback
    is set to True.
    """

    division: str
    glp_bracket: str                    # canonical label (lower bracket if merged)
    lift: str
    n_lifters: int
    slope_kg_per_day: float
    residual_std: float                 # std of per-lifter slopes in cell, kg/day
    merged_from: tuple[str, ...]        # all bracket labels combined; empty if no merge
    is_global_fallback: bool


@dataclass(frozen=True)
class MixedLMCell:
    """statsmodels MixedLM fit for one (age_division, GLP bracket, lift) cell.

    Engine D wiring (2026-04-29). The cell pools all lifters whose latest
    meet falls in (division, anchor_bracket) after applying Engine C's
    bracket-merge ladder, then fits ``lift_kg ~ years_from_first`` with
    random intercept + slope per lifter.

    The runtime path (`mixed_effects_projection`) treats this cell as a
    drop-in replacement for `GlpCohortCell` -- ``fixed_slope_kg_per_year``
    becomes the cohort term in the existing shrinkage projection math,
    converted to kg/day. Per-lifter BLUPs are intentionally not stored;
    the random-slope component is captured via ``random_slope_var`` and
    feeds the prediction-interval inflation. When ``converged`` is False,
    the runtime path falls back to the matching `GlpCohortCell` for that
    lift instead of using the (untrustworthy) failed fit's parameters.

    Variances are stored in (kg/year)^2 for slope-related fields and kg^2
    for residual; conversion to per-day at runtime divides by 365.25^2 or
    365.25 as appropriate.
    """

    division: str
    glp_bracket: str                    # canonical anchor label (lowest merged)
    lift: str
    n_lifters: int
    n_meets: int
    converged: bool
    failure_mode: str | None            # None on converge; else taxonomy label
    fixed_intercept: float              # kg
    fixed_slope_kg_per_year: float
    random_intercept_var: float         # (kg)^2
    random_slope_var: float             # (kg/year)^2
    random_cov: float                   # (kg)(kg/year)
    residual_var: float                 # (kg)^2
    merged_from: tuple[str, ...]        # all bracket labels combined; empty if no merge
    is_global_fallback: bool


@dataclass(frozen=True)
class KMTable:
    """Kaplan-Meier dropout survival per age division.

    A lifter is a dropout (event) if their last meet is > KM_DROPOUT_MONTHS
    before the dataset refresh date. A historical 18+ month gap mid-career
    does NOT make them a dropout if their most recent meet is recent.
    """

    division: str
    sample_size: int
    survival_by_month: dict[int, float]   # month -> S(month)

    def multiplier(self, horizon_months: int) -> float:
        """CI inflation factor 1 / sqrt(S(horizon)), clamped to [1.0, 3.0]."""
        if self.sample_size == 0:
            return 1.0
        h = max(1, min(int(horizon_months), 24))
        s = self.survival_by_month.get(h)
        if s is None:
            # Fall back to the latest computed survival value.
            if not self.survival_by_month:
                return 1.0
            max_known = max(m for m in self.survival_by_month if m <= h)
            s = self.survival_by_month[max_known]
        if s <= 0:
            return 3.0
        return float(max(1.0, min(3.0, 1.0 / np.sqrt(s))))


# Module-level cache. precompute_tables() fills these; endpoints read them.
_COHORT: dict[tuple[str, str, str], GlpCohortCell] = {}
_KM: dict[str, KMTable] = {}
_MIXEDLM: dict[tuple[str, str, str], MixedLMCell] = {}
_MIXEDLM_CONVERGED_PCT: float = 0.0
_ENGINE_D_GLOBAL_AVAILABLE: bool = False
_PRECOMPUTED: bool = False

# Schema version for the serialized cohort + K-M artifact. Bump when the
# GlpCohortCell, KMTable, or MixedLMCell dataclass shape changes, or when
# the fitting algorithm changes in a way that makes old artifacts wrong.
# A backend that sees a mismatched version falls back to live precompute.
# v1 -> v2 (2026-04-29): added mixedlm_cells for Engine D B-2.
SERIALIZED_TABLES_SCHEMA_VERSION: int = 2

# Production gate: Engine D is exposed to clients only when the live
# precompute clears this convergence rate across all fittable cells.
ENGINE_D_GLOBAL_GATE_THRESHOLD: float = 0.90

# MixedLM fit tunables (mirror the convergence probe so production
# behaves identically to what was probed).
_MIXEDLM_MIN_LIFTERS_PER_CELL: int = 20
_MIXEDLM_MIN_MEETS_PER_CELL: int = 60
_MIXEDLM_MAXITER: int = 200
_DAYS_PER_YEAR: float = 365.25


def is_precomputed() -> bool:
    """True once precompute_tables has succeeded at least once."""
    return _PRECOMPUTED


def get_cohort_cell(
    division: str, bracket: str, lift: str,
) -> GlpCohortCell | None:
    return _COHORT.get((division, bracket, lift))


def get_km_table(division: str) -> KMTable | None:
    return _KM.get(division)


def get_mixedlm_cell(
    division: str, bracket: str, lift: str,
) -> MixedLMCell | None:
    return _MIXEDLM.get((division, bracket, lift))


def is_engine_d_globally_available() -> bool:
    return _ENGINE_D_GLOBAL_AVAILABLE


def get_mixedlm_converged_pct() -> float:
    return _MIXEDLM_CONVERGED_PCT


def _tables_to_dict() -> dict[str, Any]:
    """Serialize the currently loaded cohort + K-M tables to a plain dict.

    Used by preprocess.py to write an on-disk artifact after fitting, and
    by load_serialized_tables() to round-trip through the test suite.

    Note on key_bracket vs glp_bracket: after bracket-merging, multiple
    dict keys can alias the same GlpCohortCell object (e.g. cells for
    "60-70" and "70-80" both resolve to the same merged cell whose
    `glp_bracket` is "60-70"). The serialised form emits one row per
    dict key and preserves `key_bracket` separately so the load side
    can rebuild the full key set without collapsing aliases.
    """
    return {
        "schema_version": SERIALIZED_TABLES_SCHEMA_VERSION,
        "cohort_cells": [
            {
                "key_bracket": key[1],
                "division": cell.division,
                "glp_bracket": cell.glp_bracket,
                "lift": cell.lift,
                "n_lifters": cell.n_lifters,
                "slope_kg_per_day": cell.slope_kg_per_day,
                "residual_std": cell.residual_std,
                "merged_from": list(cell.merged_from),
                "is_global_fallback": cell.is_global_fallback,
            }
            for key, cell in _COHORT.items()
        ],
        "km_tables": [
            {
                "division": km.division,
                "sample_size": km.sample_size,
                # JSON object keys must be strings. Round-trip reader
                # converts them back to int.
                "survival_by_month": {
                    str(month): float(prob)
                    for month, prob in km.survival_by_month.items()
                },
            }
            for km in _KM.values()
        ],
        "mixedlm_cells": [
            {
                "key_bracket": key[1],
                "division": cell.division,
                "glp_bracket": cell.glp_bracket,
                "lift": cell.lift,
                "n_lifters": cell.n_lifters,
                "n_meets": cell.n_meets,
                "converged": cell.converged,
                "failure_mode": cell.failure_mode,
                "fixed_intercept": cell.fixed_intercept,
                "fixed_slope_kg_per_year": cell.fixed_slope_kg_per_year,
                "random_intercept_var": cell.random_intercept_var,
                "random_slope_var": cell.random_slope_var,
                "random_cov": cell.random_cov,
                "residual_var": cell.residual_var,
                "merged_from": list(cell.merged_from),
                "is_global_fallback": cell.is_global_fallback,
            }
            for key, cell in _MIXEDLM.items()
        ],
        "mixedlm_converged_pct": _MIXEDLM_CONVERGED_PCT,
    }


def serialize_tables(path: "Path") -> None:
    """Write the in-memory cohort + K-M tables to ``path`` as JSON.

    The companion loader is load_serialized_tables(). Intended for
    data/preprocess.py which runs in CI after openipf.parquet is written.
    """
    import json
    from pathlib import Path as _Path

    if not isinstance(path, _Path):
        path = _Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_tables_to_dict(), f, separators=(",", ":"))
    logger.info(
        "[athlete_projection] serialized tables to %s (cells=%d km=%d)",
        path, len(_COHORT), len(_KM),
    )


def load_serialized_tables(path: "Path") -> dict[str, int]:
    """Populate module-level tables from a serialized artifact on disk.

    Replaces a full ``precompute_tables(cursor)`` call when the artifact
    was produced at preprocess time and shipped alongside the parquet.
    Drops the ~27 s fit cost on cold start.

    Raises on schema-version mismatch or structural error so the caller
    can fall back to live precompute. Never mutates the tables on
    failure -- on success, atomically replaces _COHORT, _KM, _PRECOMPUTED.

    Returns the same stats shape as precompute_tables.
    """
    import json
    from pathlib import Path as _Path

    global _COHORT, _KM, _MIXEDLM
    global _MIXEDLM_CONVERGED_PCT, _ENGINE_D_GLOBAL_AVAILABLE
    global _PRECOMPUTED

    if not isinstance(path, _Path):
        path = _Path(path)
    with path.open("r", encoding="utf-8") as f:
        doc = json.load(f)

    schema = doc.get("schema_version")
    if schema != SERIALIZED_TABLES_SCHEMA_VERSION:
        raise ValueError(
            f"serialized tables schema_version={schema!r} does not match "
            f"expected {SERIALIZED_TABLES_SCHEMA_VERSION}; falling back to live fit"
        )

    # Dedup merged-alias cells by (division, glp_bracket, lift, is_global).
    # Multiple rows with the same "cell identity" but different key_bracket
    # values resolve to the same GlpCohortCell object, matching how the
    # merge path populates _COHORT at fit time. This is load-bearing:
    # `get_cohort_cell` only reads by key tuple, but comparing cell
    # identity across the app still expects identity alias consistency.
    cohort: dict[tuple[str, str, str], GlpCohortCell] = {}
    interned: dict[tuple[Any, ...], GlpCohortCell] = {}
    for row in doc.get("cohort_cells", []):
        merged_from = tuple(row.get("merged_from") or ())
        cell_id = (
            row["division"],
            row["glp_bracket"],
            row["lift"],
            int(row["n_lifters"]),
            bool(row["is_global_fallback"]),
            merged_from,
        )
        cell = interned.get(cell_id)
        if cell is None:
            cell = GlpCohortCell(
                division=row["division"],
                glp_bracket=row["glp_bracket"],
                lift=row["lift"],
                n_lifters=int(row["n_lifters"]),
                slope_kg_per_day=float(row["slope_kg_per_day"]),
                residual_std=float(row["residual_std"]),
                merged_from=merged_from,
                is_global_fallback=bool(row["is_global_fallback"]),
            )
            interned[cell_id] = cell
        key_bracket = row.get("key_bracket") or cell.glp_bracket
        cohort[(cell.division, key_bracket, cell.lift)] = cell

    km: dict[str, KMTable] = {}
    for row in doc.get("km_tables", []):
        km_table = KMTable(
            division=row["division"],
            sample_size=int(row["sample_size"]),
            survival_by_month={
                int(month): float(prob)
                for month, prob in (row.get("survival_by_month") or {}).items()
            },
        )
        km[km_table.division] = km_table

    # MixedLM cells (Engine D B-2). Mirrors cohort interning so merged-alias
    # identity survives the round-trip.
    mixedlm: dict[tuple[str, str, str], MixedLMCell] = {}
    ml_interned: dict[tuple[Any, ...], MixedLMCell] = {}
    for row in doc.get("mixedlm_cells", []):
        merged_from = tuple(row.get("merged_from") or ())
        cell_id = (
            row["division"],
            row["glp_bracket"],
            row["lift"],
            int(row["n_lifters"]),
            bool(row["is_global_fallback"]),
            bool(row["converged"]),
            merged_from,
        )
        ml_cell = ml_interned.get(cell_id)
        if ml_cell is None:
            ml_cell = MixedLMCell(
                division=row["division"],
                glp_bracket=row["glp_bracket"],
                lift=row["lift"],
                n_lifters=int(row["n_lifters"]),
                n_meets=int(row["n_meets"]),
                converged=bool(row["converged"]),
                failure_mode=row.get("failure_mode"),
                fixed_intercept=float(row["fixed_intercept"]),
                fixed_slope_kg_per_year=float(row["fixed_slope_kg_per_year"]),
                random_intercept_var=float(row["random_intercept_var"]),
                random_slope_var=float(row["random_slope_var"]),
                random_cov=float(row["random_cov"]),
                residual_var=float(row["residual_var"]),
                merged_from=merged_from,
                is_global_fallback=bool(row["is_global_fallback"]),
            )
            ml_interned[cell_id] = ml_cell
        key_bracket = row.get("key_bracket") or ml_cell.glp_bracket
        mixedlm[(ml_cell.division, key_bracket, ml_cell.lift)] = ml_cell

    converged_pct = float(doc.get("mixedlm_converged_pct", 0.0) or 0.0)

    _COHORT = cohort
    _KM = km
    _MIXEDLM = mixedlm
    _MIXEDLM_CONVERGED_PCT = converged_pct
    _ENGINE_D_GLOBAL_AVAILABLE = converged_pct >= ENGINE_D_GLOBAL_GATE_THRESHOLD
    _PRECOMPUTED = True
    stats = {
        "cohort_cells": len(_COHORT),
        "km_tables": len(_KM),
        "mixedlm_cells": len(_MIXEDLM),
        "mixedlm_converged_pct": _MIXEDLM_CONVERGED_PCT,
    }
    logger.info(
        "[athlete_projection] loaded serialized tables cohort_cells=%d "
        "km_tables=%d mixedlm_cells=%d mixedlm_converged_pct=%.3f "
        "engine_d_global_available=%s",
        stats["cohort_cells"], stats["km_tables"], stats["mixedlm_cells"],
        stats["mixedlm_converged_pct"], _ENGINE_D_GLOBAL_AVAILABLE,
    )
    return stats


def precompute_tables(cursor=None) -> dict[str, int]:
    """Build (age_division x GLP bracket x lift) cohort cells and K-M tables.

    Idempotent. Called from FastAPI lifespan after DuckDB warmup. Failures
    are logged and the tables remain empty, causing endpoints to fall back
    to zero cohort contribution and the neutral K-M multiplier.

    Returns a small stats dict for logging: ``{"cohort_cells": n,
    "km_tables": n, "mixedlm_cells": n, "mixedlm_converged_pct": float}``.
    """
    global _COHORT, _KM, _MIXEDLM
    global _MIXEDLM_CONVERGED_PCT, _ENGINE_D_GLOBAL_AVAILABLE
    global _PRECOMPUTED
    try:
        if cursor is None:
            cursor = get_cursor()
        _COHORT = _fit_cohort_cells(cursor)
        _KM = _fit_km_tables(cursor)
        _MIXEDLM, _MIXEDLM_CONVERGED_PCT = _fit_mixedlm_cells(cursor)
        _ENGINE_D_GLOBAL_AVAILABLE = (
            _MIXEDLM_CONVERGED_PCT >= ENGINE_D_GLOBAL_GATE_THRESHOLD
        )
        _PRECOMPUTED = True
        stats = {
            "cohort_cells": len(_COHORT),
            "km_tables": len(_KM),
            "mixedlm_cells": len(_MIXEDLM),
            "mixedlm_converged_pct": _MIXEDLM_CONVERGED_PCT,
        }
        logger.info(
            "[athlete_projection] precomputed cohort_cells=%d km_tables=%d "
            "mixedlm_cells=%d mixedlm_converged_pct=%.3f "
            "engine_d_global_available=%s",
            stats["cohort_cells"], stats["km_tables"], stats["mixedlm_cells"],
            stats["mixedlm_converged_pct"], _ENGINE_D_GLOBAL_AVAILABLE,
        )
        return stats
    except Exception as exc:
        logger.exception("[athlete_projection] precompute failed: %s", exc)
        _COHORT, _KM, _MIXEDLM = {}, {}, {}
        _MIXEDLM_CONVERGED_PCT = 0.0
        _ENGINE_D_GLOBAL_AVAILABLE = False
        _PRECOMPUTED = False
        return {
            "cohort_cells": 0,
            "km_tables": 0,
            "mixedlm_cells": 0,
            "mixedlm_converged_pct": 0.0,
        }


def _load_cohort_history(cursor) -> pd.DataFrame:
    """Pull per-lifter per-meet history needed for cohort slope + K-M fitting.

    Scope: Canada + IPF, Raw only (v1). BW + Sex + Age non-null so the
    IPF-GL formula can be computed on every row. Division assignment uses
    Age (not free-text Division); per-lift slope fitting uses the lift
    columns directly (non-null only).
    """
    sql = f"""
        SELECT Name, Sex, Age, BodyweightKg, Date, Equipment,
               Best3SquatKg, Best3BenchKg, Best3DeadliftKg,
               TotalKg, Event
        FROM openipf
        WHERE Country = '{DEFAULT_COUNTRY}'
          AND ParentFederation = '{DEFAULT_PARENT_FEDERATION}'
          AND Age IS NOT NULL
          AND BodyweightKg IS NOT NULL
          AND Sex IS NOT NULL
          AND Equipment = 'Raw'
        ORDER BY Name, Date
    """
    return cursor.execute(sql).df()


def _fit_cohort_cells(
    cursor,
) -> dict[tuple[str, str, str], GlpCohortCell]:
    """Fit the (age_division x GLP bracket x lift) 2D cohort matrix.

    Steps:
      1. Pull Canada + IPF + Raw history with non-null BW/Sex/Age.
      2. Per lifter: compute latest valid TotalKg's IPF-GL score, derive
         their GLP bracket + age division from that row.
      3. Fit per-lifter Huber slope per lift (if >=3 meets contesting it).
      4. Bucket slopes into (division, bracket, lift) cells.
      5. Apply merge-fallback: sparse cells merge upward first, then downward,
         within the same division. Entire-division-too-small falls back to
         division-level mean slope across ALL brackets for that lift.
    """
    hist = _load_cohort_history(cursor)
    if hist.empty:
        return {}

    hist["AgeDivision"] = hist["Age"].apply(age_to_category)
    hist = hist[hist["AgeDivision"].isin(AGE_DIVISIONS)]
    if hist.empty:
        return {}

    # Per-lifter: assign (division, bracket) from their latest SBD meet with
    # non-null TotalKg. Fall back to the latest meet of any kind if no SBD.
    hist_sorted = hist.sort_values(["Name", "Date"])
    last_sbd = hist_sorted[hist_sorted["Event"] == "SBD"]
    last_sbd = last_sbd[last_sbd["TotalKg"].notna()]
    latest_per_name = last_sbd.groupby("Name").tail(1) if not last_sbd.empty else last_sbd

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

    # Per-lifter, per-lift Huber slope -> accumulate into cell bucket.
    cell_slopes: dict[tuple[str, str, str], list[float]] = {}
    for name, group in hist_sorted.groupby("Name", sort=False):
        if name not in name_assignment:
            continue
        division, bracket = name_assignment[name]
        for lift, col in LIFT_COLS.items():
            lift_rows = group[group[col].notna()]
            if len(lift_rows) < 3:
                continue
            lift_dates = pd.to_datetime(lift_rows["Date"].values)
            days = ((lift_dates - lift_dates[0]) / np.timedelta64(1, "D")).astype(float)
            vals = lift_rows[col].astype(float).to_numpy()
            if len(np.unique(days)) < 2:
                continue
            fit = _robust_slope(days, vals)
            if fit is None:
                continue
            slope, _i, _r = fit
            if not np.isfinite(slope) or abs(slope) > 5.0:
                continue
            key = (division, bracket, lift)
            cell_slopes.setdefault(key, []).append(float(slope))

    out: dict[tuple[str, str, str], GlpCohortCell] = {}
    for division in AGE_DIVISIONS:
        for lift in LIFT_KEYS:
            _build_division_cells(cell_slopes, division, lift, out)
    return out


def _build_division_cells(
    cell_slopes: dict[tuple[str, str, str], list[float]],
    division: str,
    lift: str,
    out: dict[tuple[str, str, str], GlpCohortCell],
) -> None:
    """Fill the 11 bracket cells for one (division, lift) pair.

    Algorithm:
      - If a cell meets MIN_COHORT_CELL_SIZE alone, emit as-is.
      - Otherwise merge upward with the next unassigned bracket until the
        combined count reaches the minimum, then downward if still short.
      - If the entire division has fewer than MIN across all brackets,
        store a division-global-fallback cell for every bracket with the
        mean of all collected slopes.
    """
    brackets = list(GLP_BRACKET_LABELS)

    total_in_div = sum(
        len(cell_slopes.get((division, b, lift), [])) for b in brackets
    )
    if total_in_div == 0:
        # No data at all; silent zero fallback so endpoints don't crash.
        for b in brackets:
            out[(division, b, lift)] = GlpCohortCell(
                division=division, glp_bracket=b, lift=lift,
                n_lifters=0, slope_kg_per_day=0.0, residual_std=0.0,
                merged_from=(), is_global_fallback=True,
            )
        return

    if total_in_div < MIN_COHORT_CELL_SIZE:
        # Whole division too small: division-global fallback.
        all_slopes: list[float] = []
        for b in brackets:
            all_slopes.extend(cell_slopes.get((division, b, lift), []))
        mean_slope = float(np.mean(all_slopes)) if all_slopes else 0.0
        resid_std = float(np.std(all_slopes)) if all_slopes else 0.0
        logger.info(
            "[athlete_projection] division %s/%s total n=%d < %d -> global fallback",
            division, lift, total_in_div, MIN_COHORT_CELL_SIZE,
        )
        merged = tuple(brackets)
        for b in brackets:
            out[(division, b, lift)] = GlpCohortCell(
                division=division, glp_bracket=b, lift=lift,
                n_lifters=total_in_div, slope_kg_per_day=mean_slope,
                residual_std=resid_std,
                merged_from=merged,
                is_global_fallback=True,
            )
        return

    # Iterate low -> high, merge sparse with neighbours as needed.
    assigned = [False] * len(brackets)
    for i in range(len(brackets)):
        if assigned[i]:
            continue
        merged_labels = [brackets[i]]
        accumulated: list[float] = list(
            cell_slopes.get((division, brackets[i], lift), [])
        )

        # Merge upward while short.
        j = i + 1
        while len(accumulated) < MIN_COHORT_CELL_SIZE and j < len(brackets):
            if assigned[j]:
                j += 1
                continue
            accumulated.extend(cell_slopes.get((division, brackets[j], lift), []))
            merged_labels.append(brackets[j])
            assigned[j] = True
            j += 1

        # Merge downward if still short.
        k = i - 1
        while len(accumulated) < MIN_COHORT_CELL_SIZE and k >= 0:
            if assigned[k]:
                k -= 1
                continue
            accumulated = list(cell_slopes.get((division, brackets[k], lift), [])) + accumulated
            merged_labels.insert(0, brackets[k])
            assigned[k] = True
            k -= 1

        if len(merged_labels) > 1:
            logger.info(
                "[athlete_projection] merged %s %s [%s] -> n=%d",
                division, lift, ",".join(merged_labels), len(accumulated),
            )

        mean_slope = float(np.mean(accumulated)) if accumulated else 0.0
        resid_std = float(np.std(accumulated)) if accumulated else 0.0
        merged_tuple = tuple(merged_labels) if len(merged_labels) > 1 else ()
        cell = GlpCohortCell(
            division=division,
            glp_bracket=merged_labels[0],
            lift=lift,
            n_lifters=len(accumulated),
            slope_kg_per_day=mean_slope,
            residual_std=resid_std,
            merged_from=merged_tuple,
            is_global_fallback=False,
        )
        for label in merged_labels:
            out[(division, label, lift)] = cell
        assigned[i] = True


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
                    random_slope_var=0.0,
                    random_cov=0.0,
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
                        random_slope_var=0.0,
                        random_cov=0.0,
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
                re_formula="~years_from_first",
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

    cov_re_arr = (
        np.asarray(result.cov_re) if result.cov_re is not None else None
    )
    if cov_re_arr is not None and cov_re_arr.size >= 4:
        ri_var = float(cov_re_arr[0, 0])
        rs_var = float(cov_re_arr[1, 1])
        rcov = float(cov_re_arr[0, 1])
    else:
        ri_var, rs_var, rcov = 0.0, 0.0, 0.0

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
        random_slope_var=rs_var,
        random_cov=rcov,
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
        random_slope_var=0.0,
        random_cov=0.0,
        residual_var=0.0,
        merged_from=merged_from,
        is_global_fallback=False,
    )


def _fit_km_tables(cursor) -> dict[str, KMTable]:
    """Kaplan-Meier survival per age division.

    Event = "dropout" (last meet > 18 months before T_refresh).
    Censored = "still active" (last meet within 18 months of T_refresh).
    """
    sql = f"""
        SELECT Name, Age, MIN(Date) AS FirstDate, MAX(Date) AS LastDate
        FROM openipf
        WHERE Country = '{DEFAULT_COUNTRY}'
          AND ParentFederation = '{DEFAULT_PARENT_FEDERATION}'
          AND Age IS NOT NULL
        GROUP BY Name, Age
    """
    df = cursor.execute(sql).df()
    if df.empty:
        return {}

    # Use the latest LastDate in the dataset as the refresh anchor; this is
    # more deterministic than datetime.now() for tests and matches the
    # spec's "T_refresh = dataset refresh date".
    df["FirstDate"] = pd.to_datetime(df["FirstDate"])
    df["LastDate"] = pd.to_datetime(df["LastDate"])
    t_refresh = df["LastDate"].max()
    df["AgeDivision"] = df["Age"].apply(age_to_category)
    df = df[df["AgeDivision"].isin(AGE_DIVISIONS)]

    # Career-length months and dropout flag.
    career_days = (df["LastDate"] - df["FirstDate"]) / np.timedelta64(1, "D")
    refresh_gap_days = (t_refresh - df["LastDate"]) / np.timedelta64(1, "D")
    df["career_months"] = (career_days / DAYS_PER_MONTH).round().astype(int)
    df["is_dropout"] = (refresh_gap_days / DAYS_PER_MONTH) > KM_DROPOUT_MONTHS

    out: dict[str, KMTable] = {}
    for division in AGE_DIVISIONS:
        sub = df[df["AgeDivision"] == division]
        if sub.empty:
            continue
        survival = _kaplan_meier_by_month(
            sub["career_months"].to_numpy(), sub["is_dropout"].to_numpy()
        )
        out[division] = KMTable(
            division=division,
            sample_size=len(sub),
            survival_by_month=survival,
        )
    return out


def _kaplan_meier_by_month(
    durations_months: np.ndarray,
    is_dropout: np.ndarray,
) -> dict[int, float]:
    """Simple K-M estimator on monthly buckets, returning S(m) for m in 0..24.

    Sort by duration. At each event (dropout) time, S *= (1 - d_i / n_i).
    Censored observations (is_dropout=False) leave the risk set without
    triggering a probability update.
    """
    n = len(durations_months)
    if n == 0:
        return {m: 1.0 for m in range(25)}

    order = np.argsort(durations_months, kind="stable")
    durations = np.asarray(durations_months)[order].astype(int)
    events = np.asarray(is_dropout)[order].astype(bool)

    survival: dict[int, float] = {}
    s = 1.0
    at_risk = n
    i = 0
    for m in range(25):
        # Count events (dropouts) at month m and censored at month m.
        n_events_m = 0
        n_censored_m = 0
        while i < n and durations[i] == m:
            if events[i]:
                n_events_m += 1
            else:
                n_censored_m += 1
            i += 1
        if at_risk > 0 and n_events_m > 0:
            s *= (1.0 - n_events_m / at_risk)
        survival[m] = s
        at_risk -= (n_events_m + n_censored_m)
        if at_risk <= 0:
            # Freeze at current S for later months.
            for later in range(m + 1, 25):
                survival[later] = s
            return survival
    return survival


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
            "precomputed": _PRECOMPUTED,
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


def _robust_slope(
    days: np.ndarray,
    values: np.ndarray,
) -> tuple[float, float, float] | None:
    """Fit (slope, intercept, residual_std) via Huber RLM. Fall back to polyfit."""
    if len(days) < 2 or len(np.unique(days)) < 2:
        return None
    days_f = np.asarray(days, dtype=float)
    vals_f = np.asarray(values, dtype=float)
    try:
        import statsmodels.api as sm
        from statsmodels.tools.sm_exceptions import ConvergenceWarning
        x = sm.add_constant(days_f, has_constant="add")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            warnings.simplefilter("ignore", RuntimeWarning)
            result = sm.RLM(vals_f, x, M=sm.robust.norms.HuberT()).fit(maxiter=50)
        intercept = float(result.params[0])
        slope = float(result.params[1])
        if not (np.isfinite(slope) and np.isfinite(intercept)):
            raise ValueError("RLM returned non-finite")
        predicted = slope * days_f + intercept
        resid_std = float(np.std(vals_f - predicted))
        return slope, intercept, resid_std
    except Exception:
        try:
            coeffs = np.polyfit(days_f, vals_f, 1)
            slope, intercept = float(coeffs[0]), float(coeffs[1])
            predicted = slope * days_f + intercept
            resid_std = float(np.std(vals_f - predicted))
            return slope, intercept, resid_std
        except Exception:
            return None


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
# Mixed-effects engine (Engine D)
# =============================================================================


def _mixedlm_to_virtual_cohort_cell(
    ml_cell: MixedLMCell,
) -> GlpCohortCell:
    """Synthesize a `GlpCohortCell` from a converged `MixedLMCell`.

    The runtime path treats Engine D as "Engine C with MixedLM-derived
    cohort numbers": only `slope_kg_per_day` and `residual_std` are read
    by `_project_single_lift`, so wrapping the MixedLM fixed slope and
    random-slope std in the existing dataclass lets the projection math
    stay shared. Conversion:
      slope_kg_per_day = fixed_slope_kg_per_year / 365.25
      residual_std     = sqrt(random_slope_var) / 365.25
    The std reflects "how much an individual lifter's slope is expected
    to differ from the cohort mean," which is what the Engine C PI
    formula expects (`seg_sigma_cohort * km_mult * t_offset`).
    """
    slope_per_day = ml_cell.fixed_slope_kg_per_year / _DAYS_PER_YEAR
    rs_std_per_year = float(np.sqrt(max(ml_cell.random_slope_var, 0.0)))
    rs_std_per_day = rs_std_per_year / _DAYS_PER_YEAR
    return GlpCohortCell(
        division=ml_cell.division,
        glp_bracket=ml_cell.glp_bracket,
        lift=ml_cell.lift,
        n_lifters=ml_cell.n_lifters,
        slope_kg_per_day=slope_per_day,
        residual_std=rs_std_per_day,
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

    if initial_bracket is None or not _MIXEDLM:
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
    engine_d_available = _ENGINE_D_GLOBAL_AVAILABLE and not all_fell_back

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


# =============================================================================
# Serialization helpers
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
