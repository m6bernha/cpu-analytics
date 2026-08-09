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

SLOPE_DAMPING_TAU_DAYS: float | None = 60.0
"""Time constant for the saturating slope, in days. None = no damping.

Projected gain is `slope * tau * (1 - exp(-t / tau))` rather than
`slope * t`, so the gain approaches an asymptote of `slope * tau` instead
of growing without bound. The instantaneous rate at t=0 is still exactly
`slope`, so near-term projections are unchanged in character.

Set from the offline backtest, see docs/adr/0005. Engine C without damping
measured a signed bias of +5.09% at 12 months and +12.06% at 36, against
its own 36-month MAPE of 12.72%: the error was almost entirely
one-directional overshoot, and it came from the slope rather than the
level convention.

60 days was chosen from a sweep of 30 / 45 / 60 / 90 / 120 / 180. All of
30 through 90 pass every ship gate; 120 and 180 fail the 12-month bias
gate. Within the passing set the choice is a trade, because a shorter
constant suits long-history lifters and a longer one suits the climbing
and short-history groups. 60 minimises the WORST bias across career-stage
strata (2.31 pp, versus 2.64 at tau=30 and 2.60 at tau=90), keeps
headroom on the tightest gate (+1.55 pp against a +/-2.0 limit), and its
MAPE is within 0.01 pp of the best candidate.

Do not raise it past 90 without re-running the sweep: the 12-month bias
gate fails at 120.
"""
