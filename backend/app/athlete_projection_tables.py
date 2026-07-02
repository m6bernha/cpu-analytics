"""Athlete Projection -- precomputed cohort + K-M + MixedLM tables.

This module owns the shared foundation of the projection engines:

  - The frozen table dataclasses (GlpCohortCell, MixedLMCell, KMTable).
  - The module-level table state (_COHORT, _KM, _MIXEDLM, ...) populated
    once at FastAPI startup and read by both engines on every request.
  - precompute_tables / serialize_tables / load_serialized_tables, the
    startup + preprocess entry points that fill or restore that state.
  - The cohort and Kaplan-Meier fitting code, plus the shared Huber
    robust-slope util used by both cohort fitting and Engine C.

IMPORTANT: the state globals here are rebound (not mutated) by
precompute_tables and load_serialized_tables. Read them through this
module (``tables._COHORT``) or via the getter functions -- a
``from ... import _COHORT`` snapshot goes stale after the next rebind.
The ``athlete_projection`` facade deliberately does NOT re-export them.

Engine C lives in athlete_projection_engine_c.py, Engine D in
athlete_projection_engine_d.py, and athlete_projection.py re-exports the
public surface of all three.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Any, Literal

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
    KM_DROPOUT_MONTHS,
    MIN_COHORT_CELL_SIZE,
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


# =============================================================================
# Table dataclasses (frozen; immutable by default)
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
    random intercept per lifter (no random slope, P5 path 2 simplification
    landed 2026-05-01). Every lifter shares the cohort slope; only their
    starting level is allowed to vary.

    The runtime path (`mixed_effects_projection`) treats this cell as a
    drop-in replacement for `GlpCohortCell` -- ``fixed_slope_kg_per_year``
    becomes the cohort term in the existing shrinkage projection math,
    converted to kg/day. Per-lifter BLUPs are intentionally not stored.
    Cohort uncertainty is now derived from ``residual_var`` (per-meet
    noise around the cohort line) rather than the previous random-slope
    variance, since intercept-only models have no per-lifter slope
    variance to capture. When ``converged`` is False, the runtime path
    falls back to the matching `GlpCohortCell` for that lift instead of
    using the (untrustworthy) failed fit's parameters.

    Variances are stored in (kg)^2; conversion to per-day at runtime
    divides by 365.25 as appropriate.
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
# v2 -> v3 (2026-05-01): random_slope_var/random_cov dropped from MixedLMCell
# (P5 path 2: random-intercept-only model).
SERIALIZED_TABLES_SCHEMA_VERSION: int = 3

# Production gate: Engine D is exposed to clients only when the live
# precompute clears this convergence rate across all fittable cells.
# Live full-scale convergence stabilizes at ~71%; we accept that ~29%
# of cells silently fall back to Engine C per-lift via meta.engine_d_partial.
# Revisit when the random-effects structure is simplified (P5 path 2).
ENGINE_D_GLOBAL_GATE_THRESHOLD: float = 0.70


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


def get_mixedlm_cell_count() -> int:
    """Number of MixedLM cells currently loaded (0 when Engine D is absent)."""
    return len(_MIXEDLM)


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
    # Imported inside the function: engine_d imports this module at load
    # time, so a top-level import here would be circular. Precompute runs
    # once per startup; the per-call import cost is irrelevant.
    from .athlete_projection_engine_d import _fit_mixedlm_cells

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


def _robust_slope(
    days: np.ndarray,
    values: np.ndarray,
) -> tuple[float, float, float] | None:
    """Fit (slope, intercept, residual_std) via Huber RLM. Fall back to polyfit.

    Shared between cohort fitting (per-lifter slopes above) and Engine C's
    personal-slope fit in athlete_projection_engine_c.py.
    """
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
