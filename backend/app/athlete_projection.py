"""Athlete Projection -- facade over the split projection modules.

The implementation was split out of this file on 2026-07-01:

  - athlete_projection_tables.py    table dataclasses, module-level state,
                                    precompute / serialize / load, cohort +
                                    K-M fitting, shared _robust_slope util
  - athlete_projection_engine_c.py  Engine C (Bayesian shrinkage, default)
  - athlete_projection_engine_d.py  Engine D (MixedLM, advanced toggle)

This module re-exports the public surface so existing imports keep
working (main.py's ``athlete_proj_mod``, scout.py's
``shrinkage_projection``, data/preprocess.py's ``precompute_tables`` /
``serialize_tables``, and the offline backtest / probe scripts).

Deliberately NOT re-exported: the mutable state globals (_COHORT, _KM,
_MIXEDLM, _MIXEDLM_CONVERGED_PCT, _ENGINE_D_GLOBAL_AVAILABLE,
_PRECOMPUTED). precompute_tables and load_serialized_tables REBIND those
names, so a ``from`` import taken here would silently go stale. Read or
patch them on ``backend.app.athlete_projection_tables`` directly, or use
the getter functions (is_precomputed, get_cohort_cell, ...).
"""

from __future__ import annotations

from .constants import (
    CURRENT_LEVEL_WINDOW,
    DAYS_PER_MONTH,
    HORIZON_MONTHS_HARD_CAP,
    HORIZON_MONTHS_SMALL_N_CAP,
    HORIZON_MONTHS_WARN,
    KM_DROPOUT_MONTHS,
    MIN_COHORT_CELL_SIZE,
    OUTLIER_SIGMA,
    SHRINKAGE_K,
    SMALL_N_THRESHOLD,
    Z_95,
)
from .data import get_cursor
from .ipf_gl_points import (
    GLP_BRACKET_LABELS,
    assign_glp_bracket,
    ipf_gl_points,
)
from .progression import age_to_category
from .athlete_projection_tables import (
    AGE_DIVISIONS,
    ENGINE_D_GLOBAL_GATE_THRESHOLD,
    Engine,
    GlpCohortCell,
    KMTable,
    LIFT_COLS,
    LIFT_KEYS,
    Lift,
    MixedLMCell,
    SERIALIZED_TABLES_SCHEMA_VERSION,
    _build_division_cells,
    _fit_cohort_cells,
    _fit_km_tables,
    _kaplan_meier_by_month,
    _load_cohort_history,
    _robust_slope,
    _tables_to_dict,
    get_cohort_cell,
    get_km_table,
    get_mixedlm_cell,
    get_mixedlm_cell_count,
    get_mixedlm_converged_pct,
    is_engine_d_globally_available,
    is_precomputed,
    load_serialized_tables,
    precompute_tables,
    serialize_tables,
)
from .athlete_projection_engine_c import (
    AthleteProjectionResult,
    LiftProjection,
    _DIVISION_TEXT_MAP,
    _aggregate_total,
    _assign_division,
    _clamp_horizon,
    _compute_brackets_per_point,
    _compute_lifter_glp,
    _is_outlier_latest,
    _load_lifter_history,
    _project_single_lift,
    compute_current_level,
    shrinkage_projection,
    to_response_dict,
)
from .athlete_projection_engine_d import (
    _failed_mixedlm_cell,
    _fit_mixedlm_cells,
    _fit_one_mixedlm_cell,
    _mixedlm_to_virtual_cohort_cell,
    mixed_effects_projection,
)

__all__ = [
    # constants + shared helpers re-exported for the offline scripts
    "CURRENT_LEVEL_WINDOW",
    "DAYS_PER_MONTH",
    "HORIZON_MONTHS_HARD_CAP",
    "HORIZON_MONTHS_SMALL_N_CAP",
    "HORIZON_MONTHS_WARN",
    "KM_DROPOUT_MONTHS",
    "MIN_COHORT_CELL_SIZE",
    "OUTLIER_SIGMA",
    "SHRINKAGE_K",
    "SMALL_N_THRESHOLD",
    "Z_95",
    "get_cursor",
    "GLP_BRACKET_LABELS",
    "assign_glp_bracket",
    "ipf_gl_points",
    "age_to_category",
    # tables
    "AGE_DIVISIONS",
    "ENGINE_D_GLOBAL_GATE_THRESHOLD",
    "Engine",
    "GlpCohortCell",
    "KMTable",
    "LIFT_COLS",
    "LIFT_KEYS",
    "Lift",
    "MixedLMCell",
    "SERIALIZED_TABLES_SCHEMA_VERSION",
    "get_cohort_cell",
    "get_km_table",
    "get_mixedlm_cell",
    "get_mixedlm_cell_count",
    "get_mixedlm_converged_pct",
    "is_engine_d_globally_available",
    "is_precomputed",
    "load_serialized_tables",
    "precompute_tables",
    "serialize_tables",
    # Engine C
    "AthleteProjectionResult",
    "LiftProjection",
    "compute_current_level",
    "shrinkage_projection",
    "to_response_dict",
    # Engine D
    "mixed_effects_projection",
]
