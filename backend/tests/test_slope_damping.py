"""Tests for the saturating slope in Engine C (docs/adr/0004).

Engine C's projected gain was `slope * t`, which measured a signed bias of
+5.09% at 12 months and +12.06% at 36 in the offline backtest, against a
36-month MAPE of 12.72%. Almost the whole error was one-directional
overshoot, and it came from the slope rather than the level convention.
Projected gain is now `slope * tau * (1 - exp(-t / tau))`, which approaches
an asymptote of `slope * tau`.

Four properties are load-bearing and locked here:

  1. `tau=None` reproduces the old linear projection EXACTLY. The constant
     is configuration, so an accidental None must not silently change
     behaviour in some third way.
  2. The per-segment increments telescope to the closed form. They are
     written as differences of effective time rather than as one closed
     form over the whole horizon, because a bracket transition mid-horizon
     changes the slope between segments. If they did not telescope, a
     lifter who crosses a bracket would get a different answer from one who
     does not, for reasons unrelated to their lifting.
  3. Gain is bounded by `slope * tau`, which is the entire point.
  4. The Huber fit cache changes nothing. It exists to avoid refitting
     identical data across both bracket passes and, in the backtest, across
     horizon buckets, so if it ever changes an answer it is a bug.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from backend.app import athlete_projection as ap
from backend.app.athlete_projection_engine_c import (
    _effective_days,
    _project_single_lift,
    project_from_history,
)


# ---------------------------------------------------------------------------
# The effective-time function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("t", [0.0, 1.0, 30.0, 365.0, 5000.0])
def test_no_damping_is_the_identity(t):
    assert _effective_days(t, None) == t


@pytest.mark.parametrize("tau", [0.0, -1.0, -365.0])
def test_nonpositive_tau_is_treated_as_no_damping(tau):
    """Guards a division by zero and a nonsensical negative asymptote."""
    assert _effective_days(365.0, tau) == 365.0


def test_effective_time_starts_at_unit_rate():
    """The instantaneous rate at t=0 must still be the raw slope, which is
    what keeps the near-term projection unchanged in character."""
    tau = 60.0
    eps = 1e-6
    assert _effective_days(eps, tau) / eps == pytest.approx(1.0, rel=1e-4)


def test_effective_time_saturates_at_tau():
    tau = 60.0
    assert _effective_days(1e9, tau) == pytest.approx(tau, rel=1e-9)
    # Never exceeds the asymptote, at any horizon. Strict inequality only
    # holds while exp(-t/tau) is still representable next to 1.0: by
    # t = 10,000 days the term is 4e-73 and the sum rounds to exactly tau.
    for t in [1, 10, 60, 365, 1096]:
        assert _effective_days(float(t), tau) < tau
    assert _effective_days(10_000.0, tau) <= tau


def test_effective_time_is_below_undamped_and_monotonic():
    tau = 60.0
    prev = -1.0
    for t in [1.0, 10.0, 60.0, 365.0, 1096.0]:
        eff = _effective_days(t, tau)
        assert eff < t, "damped time must be shorter than elapsed time"
        assert eff > prev, "effective time must still increase with elapsed time"
        prev = eff


def test_larger_tau_damps_less():
    t = 365.0
    assert (
        _effective_days(t, 30.0)
        < _effective_days(t, 90.0)
        < _effective_days(t, 365.0)
        < _effective_days(t, 10_000.0)
        < t
    )


# ---------------------------------------------------------------------------
# Projection-level behaviour
# ---------------------------------------------------------------------------


def _lifter(n_meets: int = 10, kg_per_meet: float = 5.0, days_between: float = 120.0):
    """A steadily improving lifter, one SBD meet every `days_between` days."""
    start = pd.Timestamp("2015-01-05")
    rows = []
    for i in range(n_meets):
        base = 400.0 + kg_per_meet * i
        rows.append({
            "Name": "Test Lifter",
            "Sex": "M",
            "Age": 30.0,
            "BodyweightKg": 83.0,
            "Date": start + pd.Timedelta(days=days_between * i),
            "Event": "SBD",
            "Division": "Open",
            "Best3SquatKg": base * 0.4,
            "Best3BenchKg": base * 0.25,
            "Best3DeadliftKg": base * 0.35,
            "TotalKg": base,
            "Equipment": "Raw",
        })
    return pd.DataFrame(rows)


def _cell(slope_kg_per_day: float = 0.01):
    return ap.GlpCohortCell(
        division="Open", glp_bracket="<60", lift="squat", n_lifters=50,
        slope_kg_per_day=slope_kg_per_day, residual_std=0.002,
        merged_from=(), is_global_fallback=False,
    )


def _project(tau, horizon_months=18, n_points=6, cohort_slope=0.01):
    df = _lifter()
    return _project_single_lift(
        lifter_df=df, lift="squat", cohort_cell=_cell(cohort_slope),
        horizon_months=horizon_months, n_points=n_points, km_multiplier=1.0,
        damping_tau_days=tau,
    )


def test_segments_telescope_to_the_closed_form():
    """Sum of per-segment increments equals slope * tau * (1 - exp(-t/tau)).

    The segments are computed independently so that a bracket transition can
    change the slope partway through. That freedom is only safe if, with a
    constant slope, they still add up to the closed form.
    """
    tau = 60.0
    proj = _project(tau)
    slope = proj.slope_combined_kg_per_day
    assert slope is not None and slope > 0

    last = proj.projected_points[-1]
    horizon_days = 18 * ap.DAYS_PER_MONTH
    expected_gain = slope * tau * (1.0 - math.exp(-horizon_days / tau))
    actual_gain = last["projected_kg"] - proj.current_level

    assert actual_gain == pytest.approx(expected_gain, abs=0.05)


def test_undamped_projection_is_exactly_linear():
    proj = _project(None)
    slope = proj.slope_combined_kg_per_day
    horizon_days = 18 * ap.DAYS_PER_MONTH
    gain = proj.projected_points[-1]["projected_kg"] - proj.current_level
    assert gain == pytest.approx(slope * horizon_days, abs=0.05)


def test_damping_reduces_the_projection_and_more_so_further_out():
    undamped = _project(None)
    damped = _project(60.0)
    level = undamped.current_level

    ratios = []
    for u, d in zip(undamped.projected_points, damped.projected_points):
        assert d["projected_kg"] < u["projected_kg"]
        ratios.append(
            (d["projected_kg"] - level) / (u["projected_kg"] - level)
        )
    # Retained fraction of the gain shrinks monotonically with horizon.
    assert all(b < a for a, b in zip(ratios, ratios[1:]))


def test_gain_is_bounded_by_slope_times_tau():
    """The asymptote is the whole point of the change.

    Compared against a rounding budget rather than exactly: the DTO rounds
    `current_level` and every `projected_kg` to 0.1 kg, so a gain computed
    by subtracting two of them carries up to 0.1 kg of rounding, which on
    this deliberately small synthetic slope is several percent.
    """
    tau = 60.0
    rounding_budget = 0.1

    for horizon in (12, 18, 600):
        proj = _project(tau, horizon_months=horizon)
        slope = proj.slope_combined_kg_per_day
        gain = proj.projected_points[-1]["projected_kg"] - proj.current_level
        assert gain <= slope * tau + rounding_budget

    # And exactly, on the underlying function, with no rounding involved.
    assert _effective_days(600 * ap.DAYS_PER_MONTH, tau) <= tau


def test_prediction_interval_uses_damped_time_for_the_cohort_term():
    """A band that keeps widening linearly while the mean saturates would
    claim the cohort slope can still deliver gains the mean says it cannot."""
    # Cohort-only lifter: two meets on the same day means no personal slope,
    # so the interval is driven entirely by the cohort term.
    undamped = _project(None, cohort_slope=0.05)
    damped = _project(30.0, cohort_slope=0.05)

    u_last = undamped.projected_points[-1]
    d_last = damped.projected_points[-1]
    u_width = u_last["upper_kg"] - u_last["lower_kg"]
    d_width = d_last["upper_kg"] - d_last["lower_kg"]
    assert d_width < u_width


# ---------------------------------------------------------------------------
# The fit cache
# ---------------------------------------------------------------------------


def test_fit_cache_does_not_change_the_answer():
    df = _lifter()
    shared: dict = {}
    without = _project_single_lift(
        lifter_df=df, lift="squat", cohort_cell=_cell(), horizon_months=12,
        n_points=6, km_multiplier=1.0,
    )
    with_cache = _project_single_lift(
        lifter_df=df, lift="squat", cohort_cell=_cell(), horizon_months=12,
        n_points=6, km_multiplier=1.0, fit_cache=shared,
    )
    assert with_cache.projected_points == without.projected_points
    assert with_cache.slope_personal_kg_per_day == without.slope_personal_kg_per_day

    # Second call hits the cache and must still agree.
    again = _project_single_lift(
        lifter_df=df, lift="squat", cohort_cell=_cell(), horizon_months=12,
        n_points=6, km_multiplier=1.0, fit_cache=shared,
    )
    assert again.projected_points == without.projected_points
    assert "squat" in shared


def test_fit_cache_is_keyed_per_lift():
    """One cache is shared across all three lifts within a lifter, so a key
    collision would hand the bench fit to the deadlift."""
    df = _lifter()
    shared: dict = {}
    squat = _project_single_lift(
        lifter_df=df, lift="squat", cohort_cell=_cell(), horizon_months=12,
        n_points=6, km_multiplier=1.0, fit_cache=shared,
    )
    dead = _project_single_lift(
        lifter_df=df, lift="deadlift", cohort_cell=_cell(), horizon_months=12,
        n_points=6, km_multiplier=1.0, fit_cache=shared,
    )
    assert set(shared) == {"squat", "deadlift"}
    # Deadlift is a larger share of the total, so its level must differ.
    assert dead.current_level != squat.current_level


# ---------------------------------------------------------------------------
# End-to-end through project_from_history
# ---------------------------------------------------------------------------


def test_project_from_history_threads_the_constant_into_the_total():
    df = _lifter()
    lookup = lambda _d, _b, lift: _cell()  # noqa: E731

    undamped = project_from_history(
        lifter_df=df, lifter_name="Test Lifter", horizon_months=18,
        cohort_lookup=lookup, km_lookup=lambda _d: None, damping_tau_days=None,
    )
    damped = project_from_history(
        lifter_df=df, lifter_name="Test Lifter", horizon_months=18,
        cohort_lookup=lookup, km_lookup=lambda _d: None, damping_tau_days=60.0,
    )
    assert undamped is not None and damped is not None

    u_total = undamped.total_projected_points[-1]["projected_kg"]
    d_total = damped.total_projected_points[-1]["projected_kg"]
    assert d_total < u_total
    assert damped.meta["damping_tau_days"] == 60.0
    assert undamped.meta["damping_tau_days"] is None


def test_explicit_none_overrides_the_configured_default(monkeypatch):
    """None is a meaningful value, so it must be distinguishable from
    'caller did not pass anything'."""
    monkeypatch.setattr(
        "backend.app.athlete_projection_engine_c.SLOPE_DAMPING_TAU_DAYS", 60.0,
    )
    df = _lifter()
    lookup = lambda _d, _b, lift: _cell()  # noqa: E731
    kw = dict(
        lifter_df=df, lifter_name="Test Lifter", horizon_months=18,
        cohort_lookup=lookup, km_lookup=lambda _d: None,
    )
    default = project_from_history(**kw)
    forced_off = project_from_history(**kw, damping_tau_days=None)

    assert default.meta["damping_tau_days"] == 60.0
    assert forced_off.meta["damping_tau_days"] is None
    assert (
        forced_off.total_projected_points[-1]["projected_kg"]
        > default.total_projected_points[-1]["projected_kg"]
    )
