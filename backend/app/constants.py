"""Global constants and configuration shared across backend modules.

This module centralizes numeric constants, thresholds, and configuration
values to eliminate duplication and serve as a single source of truth.
Module-specific constants (e.g., STALE_DAYS_THRESHOLD in scout.py) stay
in their respective modules since they are not shared.
"""

from __future__ import annotations

# =============================================================================
# Shared statistical constants
# =============================================================================

DAYS_PER_MONTH: float = 30.44
"""Average days per month used for time-unit conversions in projections."""

Z_95: float = 1.96
"""Standard normal critical value for 95% prediction intervals."""

# =============================================================================
# Athlete Projection (Engine C) parameters
# =============================================================================

SHRINKAGE_K: int = 5
"""Shrinkage denominator: w_p = n / (n + SHRINKAGE_K).

Controls the relative weight of personal slope vs. cohort slope in the
combined projection. Higher values bias toward cohort; lower values trust
personal data more.
"""

CURRENT_LEVEL_WINDOW: int = 3
"""Number of recent lift-specific meets used to estimate current level.

Takes the max of the last CURRENT_LEVEL_WINDOW contested meets. If fewer
meets exist, uses median of all available meets.
"""

KM_DROPOUT_MONTHS: int = 18
"""Dropout censoring threshold for Kaplan-Meier estimation.

Lifters whose last meet was > KM_DROPOUT_MONTHS ago are marked as dropout
(censored at follow-up time) rather than continuing to compete.
"""

OUTLIER_SIGMA: float = 2.5
"""Threshold for flagging latest meet as statistical outlier.

If the latest meet is > OUTLIER_SIGMA standard deviations below the fit
estimate, the projection response flags this as an outlier.
"""

HORIZON_MONTHS_HARD_CAP: int = 18
"""Maximum projection horizon regardless of request parameter."""

HORIZON_MONTHS_SMALL_N_CAP: int = 6
"""Maximum projection horizon when n_meets < SMALL_N_THRESHOLD."""

HORIZON_MONTHS_WARN: int = 12
"""Projection horizon threshold for warning flag in response metadata."""

SMALL_N_THRESHOLD: int = 5
"""Meet count below which HORIZON_MONTHS_SMALL_N_CAP applies."""

MIN_COHORT_CELL_SIZE: int = 20
"""Minimum lifters per (division × bracket × lift) cell before merging."""
