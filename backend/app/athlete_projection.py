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
MIN_COHORT_LIFTERS_FOR_FIT: int = 20  # fewer than this -> global-mean fallback


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
class CohortSlopeTable:
    """Level-conditioned slope lookup for one (age_division, lift) pair.

    Primary fit: slope = a * exp(-b * level). Falls back to LOESS on the
    (level, slope) scatter, then to the global mean slope.
    """

    division: str
    lift: str
    n_samples: int                      # number of lifters contributing (level, slope) pairs
    fit_method: str                     # "exp_decay" | "loess" | "global_mean"
    a: float | None
    b: float | None
    loess_grid: tuple[float, ...] | None
    loess_slopes: tuple[float, ...] | None
    global_mean_slope: float            # kg/day; always populated
    residual_std: float                 # kg/day; std of observed slopes around fit

    def predict(self, level: float | None) -> float:
        """Return the expected slope (kg/day) at the given current level."""
        if level is None or level <= 0:
            return float(self.global_mean_slope)
        if self.fit_method == "exp_decay" and self.a is not None and self.b is not None:
            return float(self.a * np.exp(-self.b * level))
        if self.fit_method == "loess" and self.loess_grid and self.loess_slopes:
            return float(np.interp(level, self.loess_grid, self.loess_slopes))
        return float(self.global_mean_slope)


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
_COHORT: dict[tuple[str, str], CohortSlopeTable] = {}
_KM: dict[str, KMTable] = {}
_PRECOMPUTED: bool = False


def is_precomputed() -> bool:
    """True once precompute_tables has succeeded at least once."""
    return _PRECOMPUTED


def get_cohort_table(division: str, lift: str) -> CohortSlopeTable | None:
    return _COHORT.get((division, lift))


def get_km_table(division: str) -> KMTable | None:
    return _KM.get(division)


def precompute_tables(cursor=None) -> dict[str, int]:
    """Build cohort slope tables and K-M tables. Idempotent.

    Called from FastAPI lifespan after DuckDB warmup. Failures are logged
    and the tables remain empty, causing endpoints to fall back to the
    global-mean cohort slope and the neutral K-M multiplier.

    Returns a small stats dict for logging: {"cohort_tables": n, "km_tables": n}.
    """
    global _COHORT, _KM, _PRECOMPUTED
    try:
        if cursor is None:
            cursor = get_cursor()
        _COHORT = _fit_cohort_tables(cursor)
        _KM = _fit_km_tables(cursor)
        _PRECOMPUTED = True
        stats = {"cohort_tables": len(_COHORT), "km_tables": len(_KM)}
        logger.info(
            "[athlete_projection] precomputed cohort_tables=%d km_tables=%d",
            stats["cohort_tables"], stats["km_tables"],
        )
        return stats
    except Exception as exc:
        logger.exception("[athlete_projection] precompute failed: %s", exc)
        _COHORT, _KM = {}, {}
        _PRECOMPUTED = False
        return {"cohort_tables": 0, "km_tables": 0}


def _load_cohort_history(cursor) -> pd.DataFrame:
    """Pull per-lifter per-meet history needed for cohort slope + K-M fitting.

    Scope: Canada + IPF, SBD only. Age populated (cohort assignment requires
    it; bench-only meets still contribute to bench-lift slopes via the
    per-lift non-null filter downstream).
    """
    sql = f"""
        SELECT Name, Age, Date,
               Best3SquatKg, Best3BenchKg, Best3DeadliftKg,
               TotalKg, Event
        FROM openipf
        WHERE Country = '{DEFAULT_COUNTRY}'
          AND ParentFederation = '{DEFAULT_PARENT_FEDERATION}'
          AND Age IS NOT NULL
        ORDER BY Name, Date
    """
    return cursor.execute(sql).df()


def _fit_cohort_tables(cursor) -> dict[tuple[str, str], CohortSlopeTable]:
    """For each (age_division, lift), fit slope(level) = a * exp(-b * level)."""
    hist = _load_cohort_history(cursor)
    if hist.empty:
        return {}

    hist["AgeDivision"] = hist["Age"].apply(age_to_category)
    hist = hist[hist["AgeDivision"].isin(AGE_DIVISIONS)]
    if hist.empty:
        return {}

    out: dict[tuple[str, str], CohortSlopeTable] = {}
    for division in AGE_DIVISIONS:
        div_rows = hist[hist["AgeDivision"] == division]
        if div_rows.empty:
            continue
        for lift in LIFT_KEYS:
            col = LIFT_COLS[lift]
            pairs = _collect_level_slope_pairs(div_rows, col)
            out[(division, lift)] = _fit_level_conditioned(division, lift, pairs)
    return out


def _collect_level_slope_pairs(
    div_rows: pd.DataFrame,
    lift_col: str,
) -> list[tuple[float, float]]:
    """Per lifter, compute (starting_level, observed_slope) if they have 3+
    meets contesting this lift."""
    sub = div_rows[div_rows[lift_col].notna()].copy()
    if sub.empty:
        return []
    sub = sub.sort_values(["Name", "Date"])
    pairs: list[tuple[float, float]] = []
    for name, group in sub.groupby("Name", sort=False):
        if len(group) < 3:
            continue
        dates = pd.to_datetime(group["Date"].values)
        days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
        vals = group[lift_col].astype(float).to_numpy()
        if len(np.unique(days)) < 2:
            continue
        # Huber-robust slope; fall back to polyfit.
        fit = _robust_slope(days, vals)
        if fit is None:
            continue
        slope, _intercept, _resid_std = fit
        # Exclude absurd slopes (data entry errors, class changes masquerading as lift jumps).
        if not np.isfinite(slope) or abs(slope) > 5.0:  # 5 kg/day = wildly implausible
            continue
        level = float(vals[0])   # starting level
        if level <= 0:
            continue
        pairs.append((level, float(slope)))
    return pairs


def _fit_level_conditioned(
    division: str,
    lift: str,
    pairs: list[tuple[float, float]],
) -> CohortSlopeTable:
    """Try exp-decay fit, then LOESS, then global mean as the floor."""
    n = len(pairs)
    if n == 0:
        return CohortSlopeTable(
            division=division, lift=lift, n_samples=0,
            fit_method="global_mean", a=None, b=None,
            loess_grid=None, loess_slopes=None,
            global_mean_slope=0.0, residual_std=0.0,
        )

    levels = np.array([p[0] for p in pairs], dtype=float)
    slopes = np.array([p[1] for p in pairs], dtype=float)
    global_mean = float(np.mean(slopes))
    global_std = float(np.std(slopes))

    if n < MIN_COHORT_LIFTERS_FOR_FIT:
        return CohortSlopeTable(
            division=division, lift=lift, n_samples=n,
            fit_method="global_mean", a=None, b=None,
            loess_grid=None, loess_slopes=None,
            global_mean_slope=global_mean, residual_std=global_std,
        )

    # Exp decay: slope = a * exp(-b * level). a should be positive (novices
    # gain fastest), b should be >0 (gain rate decreases with level).
    try:
        from scipy.optimize import curve_fit
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            popt, _ = curve_fit(
                lambda x, a, b: a * np.exp(-b * x),
                levels, slopes,
                p0=[max(global_mean * 2, 0.1), 0.001],
                maxfev=2000,
            )
        a, b = float(popt[0]), float(popt[1])
        if np.isfinite(a) and np.isfinite(b) and b > 0 and a > 0:
            predicted = a * np.exp(-b * levels)
            resid_std = float(np.std(slopes - predicted))
            return CohortSlopeTable(
                division=division, lift=lift, n_samples=n,
                fit_method="exp_decay", a=a, b=b,
                loess_grid=None, loess_slopes=None,
                global_mean_slope=global_mean, residual_std=resid_std,
            )
    except Exception:
        pass

    # LOESS via statsmodels lowess. Smooth on (level, slope) scatter.
    try:
        from statsmodels.nonparametric.smoothers_lowess import lowess
        order = np.argsort(levels)
        smoothed = lowess(slopes[order], levels[order], frac=0.4, it=1, return_sorted=False)
        # Build an evenly-spaced grid for fast predict().
        grid = np.linspace(float(levels.min()), float(levels.max()), 60)
        grid_slopes = np.interp(grid, levels[order], smoothed)
        predicted = np.interp(levels, grid, grid_slopes)
        resid_std = float(np.std(slopes - predicted))
        return CohortSlopeTable(
            division=division, lift=lift, n_samples=n,
            fit_method="loess", a=None, b=None,
            loess_grid=tuple(grid.tolist()),
            loess_slopes=tuple(grid_slopes.tolist()),
            global_mean_slope=global_mean, residual_std=resid_std,
        )
    except Exception:
        pass

    return CohortSlopeTable(
        division=division, lift=lift, n_samples=n,
        fit_method="global_mean", a=None, b=None,
        loess_grid=None, loess_slopes=None,
        global_mean_slope=global_mean, residual_std=global_std,
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
    """Engine C: Bayesian shrinkage with Huber personal + level-conditioned cohort.

    Returns None if the lifter has no meets or no age data to assign a cohort.
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

    km = get_km_table(age_division)
    km_multiplier = km.multiplier(effective_horizon) if km else 1.0

    lift_results: dict[str, LiftProjection] = {}
    outlier_lifts: list[str] = []
    for lift in LIFT_KEYS:
        proj = _project_single_lift(
            lifter_df,
            lift=lift,
            age_division=age_division,
            horizon_months=effective_horizon,
            n_points=n_points,
            km_multiplier=km_multiplier,
        )
        lift_results[lift] = proj
        if _is_outlier_latest(lifter_df, lift, proj):
            outlier_lifts.append(lift)

    total_history, total_projected = _aggregate_total(lifter_df, lift_results, n_points)

    cohort_tables_available = sum(
        1 for lift in LIFT_KEYS if get_cohort_table(age_division, lift) is not None
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
            "cohort_tables_available": cohort_tables_available,
            "km_multiplier": km_multiplier,
            "km_sample_size": km.sample_size if km else 0,
            "precomputed": _PRECOMPUTED,
            "small_n_warning": n_total_meets < SMALL_N_THRESHOLD,
            "long_horizon_warning": horizon_months > HORIZON_MONTHS_WARN,
        },
    )


def _load_lifter_history(cursor, name: str) -> pd.DataFrame | None:
    sql = f"""
        SELECT Name, Age, Date, Event,
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


def _assign_division(lifter_df: pd.DataFrame) -> str | None:
    """Pick age division from the most recent meet's Age. None if unknown."""
    last_age = lifter_df.iloc[-1].get("Age")
    if last_age is None or pd.isna(last_age):
        return None
    div = age_to_category(float(last_age))
    if isinstance(div, str) and div in AGE_DIVISIONS:
        return div
    return None


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
    age_division: str,
    horizon_months: int,
    n_points: int,
    km_multiplier: float,
) -> LiftProjection:
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

    # Personal slope (Huber, with polyfit fallback).
    slope_personal: float | None = None
    intercept_personal: float | None = None
    sigma_personal: float | None = None
    s_xx: float | None = None
    t_mean_days: float | None = None

    if n_meets >= 2 and len(np.unique(days)) >= 2:
        fit = _robust_slope(days, np.asarray(values))
        if fit is not None:
            slope_personal, intercept_personal, sigma_personal = fit
        t_mean_days = float(np.mean(days))
        s_xx = float(np.sum((days - t_mean_days) ** 2))

    # Cohort slope (level-conditioned lookup).
    cohort_table = get_cohort_table(age_division, lift)
    slope_cohort: float | None = None
    sigma_cohort: float = 0.0
    if cohort_table is not None:
        slope_cohort = cohort_table.predict(current_level)
        sigma_cohort = cohort_table.residual_std

    # Combined slope via slope-only shrinkage. Level is NOT shrunk.
    w_personal = n_meets / (n_meets + SHRINKAGE_K)
    slope_combined: float | None = None
    if slope_personal is not None and slope_cohort is not None:
        slope_combined = w_personal * slope_personal + (1 - w_personal) * slope_cohort
    elif slope_personal is not None:
        slope_combined = slope_personal
    elif slope_cohort is not None:
        slope_combined = slope_cohort
        w_personal = 0.0  # no personal data -> pure cohort

    # Residual std for PI. Prefer personal (honest for this lifter) with
    # cohort as fallback. K-M multiplier inflates the cohort portion.
    if sigma_personal is not None and sigma_personal > 0:
        sigma_resid = float(sigma_personal)
    else:
        sigma_resid = float(sigma_cohort * km_multiplier)

    # Project forward from last_meet_day.
    projected: list[dict[str, Any]] = []
    if slope_combined is not None and current_level is not None:
        step_days = (horizon_months * DAYS_PER_MONTH) / max(1, n_points)
        for i in range(1, n_points + 1):
            future_day = last_meet_day + step_days * i
            # Level-anchored projection: start from current level, extend by slope.
            future_offset_days = future_day - last_meet_day
            pred = current_level + slope_combined * future_offset_days
            # Prediction interval: PI = sigma_resid^2 + var_params(t).
            if s_xx is not None and s_xx > 0 and sigma_personal is not None and n_meets >= 2:
                # Classical linear-regression prediction variance around t.
                var_params = sigma_personal ** 2 * (
                    1.0 / n_meets + (future_day - (t_mean_days or 0.0)) ** 2 / s_xx
                )
            else:
                # No personal fit -> lean on cohort, inflated by K-M.
                var_params = (sigma_cohort * km_multiplier) ** 2
            pi_half = Z_95 * float(np.sqrt(max(sigma_resid ** 2 + var_params, 0.0)))
            projected.append({
                "days_from_first": round(future_day, 1),
                "months_from_last": round((future_day - last_meet_day) / DAYS_PER_MONTH, 2),
                "projected_kg": round(pred, 1),
                "lower_kg": round(pred - pi_half, 1),
                "upper_kg": round(pred + pi_half, 1),
            })

    return LiftProjection(
        lift=lift,
        n_meets=n_meets,
        current_level=round(current_level, 1) if current_level is not None else None,
        slope_personal_kg_per_day=(
            round(slope_personal, 5) if slope_personal is not None else None
        ),
        slope_cohort_kg_per_day=(
            round(slope_cohort, 5) if slope_cohort is not None else None
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
# Mixed-effects engine (Engine D) -- shipped in a later commit
# =============================================================================


def mixed_effects_projection(
    lifter_name: str,
    horizon_months: int = 12,
    n_points: int = 6,
) -> AthleteProjectionResult | None:
    """Engine D: statsmodels MixedLM per lift (scaffold, not yet active).

    Returns a result with engine="mixed_effects" but delegates the numerical
    fit to shrinkage_projection until the MixedLM wiring lands in C5. The
    API endpoint checks `meta["engine_d_available"]` before exposing this
    to the frontend.
    """
    fallback = shrinkage_projection(lifter_name, horizon_months, n_points)
    if fallback is None:
        return None
    # Stamp engine label so callers see the intent; frontend should hide the
    # toggle until meta.engine_d_available is True.
    return AthleteProjectionResult(
        lifter_name=fallback.lifter_name,
        engine="mixed_effects",
        horizon_months=fallback.horizon_months,
        horizon_capped=fallback.horizon_capped,
        as_of_date=fallback.as_of_date,
        age_division=fallback.age_division,
        lifts=fallback.lifts,
        total_history=fallback.total_history,
        total_projected_points=fallback.total_projected_points,
        outlier_lifts=fallback.outlier_lifts,
        meta={**fallback.meta, "engine_d_available": False,
              "engine_d_note": "MixedLM wiring ships in a follow-up commit; using shrinkage fallback."},
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
            }
            for key, lp in result.lifts.items()
        },
        "total_history": list(result.total_history),
        "total_projected_points": list(result.total_projected_points),
        "outlier_lifts": list(result.outlier_lifts),
        "meta": result.meta,
    }
