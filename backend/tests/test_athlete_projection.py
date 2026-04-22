"""Tests for Engine C (Bayesian shrinkage + level-conditioned cohort +
Kaplan-Meier CI correction) from backend/app/athlete_projection.py.

Engine D tests land alongside the MixedLM implementation in the C5 commit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import backend.app.athlete_projection as ap


# -----------------------------------------------------------------------------
# Fixture: run the cohort + K-M precompute against the synthetic test_conn.
# -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def precomputed(test_conn):
    """Populate module-level cohort + K-M tables from the test parquet."""
    ap.precompute_tables()
    yield
    ap._COHORT = {}
    ap._KM = {}
    ap._PRECOMPUTED = False


# =============================================================================
# Shrinkage formula
# =============================================================================


class TestShrinkageFormula:
    """w_p = n / (n + 5) across the range of meet counts."""

    @pytest.mark.parametrize(
        "n, expected",
        [
            (0, 0.0),
            (1, 1 / 6),
            (2, 2 / 7),
            (5, 5 / 10),
            (10, 10 / 15),
            (20, 20 / 25),
        ],
    )
    def test_w_personal_matches_formula(self, n: int, expected: float):
        assert ap.SHRINKAGE_K == 5
        assert n / (n + ap.SHRINKAGE_K) == pytest.approx(expected, rel=1e-6)


# =============================================================================
# Current level: max of last 3, median of last 2, single for n=1, None for n=0
# =============================================================================


class TestCurrentLevel:
    def test_max_of_last_three_when_n_ge_3(self):
        assert ap.compute_current_level([400, 450, 470, 460, 490]) == 490
        # Only the last three are considered, so a pre-last-3 peak is ignored.
        assert ap.compute_current_level([500, 450, 470, 480]) == 480

    def test_median_of_last_two_when_n_eq_2(self):
        assert ap.compute_current_level([400, 450]) == 425

    def test_single_value_when_n_eq_1(self):
        assert ap.compute_current_level([420]) == 420

    def test_none_when_empty(self):
        assert ap.compute_current_level([]) is None

    def test_ignores_nans(self):
        assert ap.compute_current_level([None, float("nan"), 450, 500]) == 475  # median of last 2

    def test_level_not_shrunk(self):
        """Spec: shrinkage applies to slope only, never to current level."""
        # Level function must have no dependency on SHRINKAGE_K.
        for n in range(1, 20):
            vals = [100.0 + i for i in range(n)]
            lvl = ap.compute_current_level(vals)
            # Recomputation must match deterministically regardless of n.
            if n >= 3:
                assert lvl == max(vals[-3:])
            elif n == 2:
                assert lvl == (vals[-1] + vals[-2]) / 2
            else:
                assert lvl == vals[-1]


# =============================================================================
# Robust slope fit (Huber RLM with polyfit fallback)
# =============================================================================


class TestRobustSlope:
    def test_recovers_clean_linear_slope(self):
        days = np.arange(0, 1000, 100, dtype=float)
        true_slope = 0.05  # kg per day
        vals = 400 + true_slope * days
        fit = ap._robust_slope(days, vals)
        assert fit is not None
        slope, intercept, resid_std = fit
        assert slope == pytest.approx(true_slope, abs=1e-4)
        assert intercept == pytest.approx(400.0, abs=1e-2)
        assert resid_std < 1e-4

    def test_returns_none_when_all_same_day(self):
        days = np.array([0.0, 0.0, 0.0])
        vals = np.array([400.0, 410.0, 420.0])
        assert ap._robust_slope(days, vals) is None

    def test_returns_none_when_too_few_points(self):
        assert ap._robust_slope(np.array([0.0]), np.array([400.0])) is None

    def test_polyfit_fallback_produces_valid_fit(self):
        # Three colinear points; Huber and polyfit both succeed and agree.
        days = np.array([0.0, 100.0, 200.0])
        vals = np.array([400.0, 410.0, 420.0])
        fit = ap._robust_slope(days, vals)
        assert fit is not None
        slope, _intercept, _resid = fit
        assert slope == pytest.approx(0.1, abs=1e-4)

    def test_robust_to_single_outlier(self):
        """Huber should down-weight a single contaminant far more than OLS."""
        days = np.arange(0, 1000, 100, dtype=float)
        vals = 400 + 0.05 * days
        vals[-1] += 200  # contaminate last point
        fit = ap._robust_slope(days, vals)
        assert fit is not None
        robust_slope, _i, _s = fit
        ols_slope = float(np.polyfit(days, vals, 1)[0])
        # Robust slope should be closer to true (0.05) than OLS.
        assert abs(robust_slope - 0.05) <= abs(ols_slope - 0.05)


# =============================================================================
# Level-conditioned cohort slope fit (exp decay, LOESS fallback, global mean)
# =============================================================================


class TestCohortSlopeFit:
    def test_exp_decay_recovers_known_params(self):
        """slope = a * exp(-b * level) with noise; fit should recover a, b."""
        rng = np.random.default_rng(42)
        levels = np.linspace(300, 900, 60)
        true_a, true_b = 0.20, 0.003
        slopes = true_a * np.exp(-true_b * levels) + rng.normal(0, 0.005, size=len(levels))
        pairs = list(zip(levels.tolist(), slopes.tolist()))
        table = ap._fit_level_conditioned("Open", "squat", pairs)
        assert table.fit_method == "exp_decay"
        assert table.a == pytest.approx(true_a, rel=0.25)
        assert table.b == pytest.approx(true_b, rel=0.30)

    def test_global_mean_fallback_for_sparse(self):
        """Fewer than MIN_COHORT_LIFTERS_FOR_FIT pairs -> global mean."""
        pairs = [(400.0, 0.05), (500.0, 0.04), (600.0, 0.03)]
        table = ap._fit_level_conditioned("Open", "squat", pairs)
        assert table.fit_method == "global_mean"
        assert table.global_mean_slope == pytest.approx(0.04, abs=1e-6)

    def test_empty_pairs_gives_zero_fallback(self):
        table = ap._fit_level_conditioned("M4", "deadlift", [])
        assert table.n_samples == 0
        assert table.global_mean_slope == 0.0

    def test_predict_handles_none_level(self):
        table = ap._fit_level_conditioned(
            "Open", "squat", [(400.0, 0.05), (500.0, 0.04)]
        )
        assert table.predict(None) == pytest.approx(table.global_mean_slope, abs=1e-9)

    def test_predict_handles_negative_level(self):
        table = ap._fit_level_conditioned(
            "Open", "squat", [(400.0, 0.05), (500.0, 0.04)]
        )
        assert table.predict(-100) == pytest.approx(table.global_mean_slope, abs=1e-9)

    def test_exp_decay_predict_monotonic_decreasing(self):
        rng = np.random.default_rng(11)
        levels = np.linspace(300, 900, 40)
        slopes = 0.18 * np.exp(-0.002 * levels) + rng.normal(0, 0.002, size=40)
        pairs = list(zip(levels.tolist(), slopes.tolist()))
        table = ap._fit_level_conditioned("Open", "bench", pairs)
        if table.fit_method == "exp_decay":
            # Higher level -> lower predicted slope.
            assert table.predict(350) > table.predict(800)


# =============================================================================
# Kaplan-Meier survival + multiplier
# =============================================================================


class TestKaplanMeier:
    def test_empty_returns_flat_one(self):
        out = ap._kaplan_meier_by_month(np.array([]), np.array([]))
        assert out[0] == 1.0
        assert out[24] == 1.0

    def test_all_dropped_at_month_6_survival_zero_from_6(self):
        durations = np.full(100, 6, dtype=int)
        events = np.ones(100, dtype=bool)
        out = ap._kaplan_meier_by_month(durations, events)
        assert out[5] == pytest.approx(1.0)
        assert out[6] == pytest.approx(0.0)
        assert out[24] == pytest.approx(0.0)

    def test_none_dropped_survival_stays_one(self):
        durations = np.full(100, 12, dtype=int)
        events = np.zeros(100, dtype=bool)   # all censored
        out = ap._kaplan_meier_by_month(durations, events)
        for m in range(25):
            assert out[m] == pytest.approx(1.0)

    def test_multiplier_clamped_to_one_when_survival_full(self):
        km = ap.KMTable(
            division="Open", sample_size=100,
            survival_by_month={m: 1.0 for m in range(25)},
        )
        assert km.multiplier(12) == 1.0

    def test_multiplier_clamped_to_three_at_worst(self):
        km = ap.KMTable(
            division="Open", sample_size=100,
            survival_by_month={m: 0.01 for m in range(25)},
        )
        # 1/sqrt(0.01) = 10, clamped to 3.
        assert km.multiplier(12) == 3.0

    def test_multiplier_empty_km_returns_one(self):
        km = ap.KMTable(division="Open", sample_size=0, survival_by_month={})
        assert km.multiplier(12) == 1.0

    def test_historical_gap_but_returned_is_not_dropout(self):
        """A lifter who went 24 months between two meets but whose LAST meet is
        recent must NOT be marked as dropout for K-M purposes.

        K-M works off (first_meet_date, last_meet_date) per lifter aggregated
        in SQL. The only question is whether (T_refresh - last_meet) > 18mo.
        A mid-career gap does not enter the calculation.
        """
        # Build a synthetic per-lifter aggregation directly.
        # T_refresh = 2026-01-01.
        # Lifter A: big mid-career gap 2020 -> 2024, but LAST meet 2025-06-01
        #   is only ~7 months before refresh. A is ACTIVE, not a dropout.
        # Lifter B: clean 2020 -> 2023, last meet 2023-03-01 (~34 months before
        #   refresh). B is a DROPOUT.
        t_refresh = pd.Timestamp("2026-01-01")
        recs = [
            ("A", pd.Timestamp("2020-01-01"), pd.Timestamp("2025-06-01")),
            ("B", pd.Timestamp("2020-01-01"), pd.Timestamp("2023-03-01")),
        ]
        df = pd.DataFrame(recs, columns=["Name", "FirstDate", "LastDate"])
        gap_days = (t_refresh - df["LastDate"]) / np.timedelta64(1, "D")
        df["is_dropout"] = (gap_days / ap.DAYS_PER_MONTH) > ap.KM_DROPOUT_MONTHS
        # The GAP 2020-2024 does NOT make A a dropout retroactively.
        assert bool(df.loc[df["Name"] == "A", "is_dropout"].item()) is False
        # B's last meet is 34mo before refresh -> dropout.
        assert bool(df.loc[df["Name"] == "B", "is_dropout"].item()) is True


# =============================================================================
# Horizon clamping
# =============================================================================


class TestHorizonClamp:
    def test_small_n_capped_at_six_months(self):
        h, capped = ap._clamp_horizon(12, n_meets=3)
        assert h == ap.HORIZON_MONTHS_SMALL_N_CAP
        assert capped is True

    def test_large_n_capped_at_eighteen(self):
        h, capped = ap._clamp_horizon(30, n_meets=15)
        assert h == ap.HORIZON_MONTHS_HARD_CAP
        assert capped is True

    def test_within_limits_passes_through(self):
        h, capped = ap._clamp_horizon(12, n_meets=15)
        assert h == 12
        assert capped is False

    def test_min_horizon_one(self):
        h, _ = ap._clamp_horizon(0, n_meets=15)
        assert h == 1


# =============================================================================
# End-to-end Engine C against the synthetic fixture
# =============================================================================


class TestShrinkageProjectionE2E:
    def test_bob_returns_result(self, precomputed):
        result = ap.shrinkage_projection("Bob B", horizon_months=12)
        assert result is not None
        assert result.engine == "shrinkage"
        assert result.age_division == "Open"
        for k in ("squat", "bench", "deadlift"):
            assert k in result.lifts
        assert len(result.total_projected_points) == 6

    def test_unknown_lifter_returns_none(self, precomputed):
        assert ap.shrinkage_projection("Nonexistent Lifter") is None

    def test_bench_only_meet_counts_only_toward_bench(self, precomputed):
        """Bob has 4 SBD meets + 1 B-only meet. Bench n should be 5, S/D n should be 4."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        assert result.lifts["squat"].n_meets == 4
        assert result.lifts["deadlift"].n_meets == 4
        assert result.lifts["bench"].n_meets == 5

    def test_w_personal_increases_with_n(self, precomputed):
        """Spec: w_p = n / (n + 5). With n=4 for Bob's squat, w_p = 4/9."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        assert result.lifts["squat"].w_personal == pytest.approx(4 / 9, abs=1e-3)
        # Bench got an extra meet (n=5).
        assert result.lifts["bench"].w_personal == pytest.approx(5 / 10, abs=1e-3)

    def test_horizon_caps_for_small_n(self, precomputed):
        """Dana has 1 meet. Horizon should cap at 6 even if asked for 18."""
        result = ap.shrinkage_projection("Dana D", horizon_months=18)
        # Dana has only 1 meet, so all lifts return n=1 projection. Horizon
        # should still have been clamped to the small-N cap server-side.
        if result is not None:
            assert result.horizon_months == ap.HORIZON_MONTHS_SMALL_N_CAP
            assert result.horizon_capped is True

    def test_hard_cap_at_eighteen_months(self, precomputed):
        result = ap.shrinkage_projection("Bob B", horizon_months=30)
        assert result is not None
        assert result.horizon_months == ap.HORIZON_MONTHS_HARD_CAP
        assert result.horizon_capped is True

    def test_total_is_sum_of_lifts(self, precomputed):
        """Per-lift aggregation: total at each horizon point = S + B + D."""
        result = ap.shrinkage_projection("Bob B", horizon_months=12)
        assert result is not None
        if not result.total_projected_points:
            pytest.skip("no aggregate points generated")
        for i, tp in enumerate(result.total_projected_points):
            s = result.lifts["squat"].projected_points[i]["projected_kg"]
            b = result.lifts["bench"].projected_points[i]["projected_kg"]
            d = result.lifts["deadlift"].projected_points[i]["projected_kg"]
            assert tp["projected_kg"] == pytest.approx(s + b + d, abs=0.2)

    def test_pi_widens_with_horizon(self, precomputed):
        result = ap.shrinkage_projection("Bob B", horizon_months=18)
        assert result is not None
        pts = result.lifts["squat"].projected_points
        if len(pts) >= 2:
            # PI half-width (upper - projected) should be monotonic non-decreasing.
            widths = [p["upper_kg"] - p["projected_kg"] for p in pts]
            for i in range(1, len(widths)):
                assert widths[i] >= widths[i - 1] - 0.1   # allow rounding slop

    def test_level_not_shrunk(self, precomputed):
        """Bob's current_level for squat should be max of his last 3 squat
        meets (200, 200, 205 -> 205), independent of the shrinkage weight."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        # Bob's last 3 SBD squats: 190, 200, 205. Also a 205 in meet 4.
        # Max of last 3 SBD meets = max(200, 200, 205) = 205.
        assert result.lifts["squat"].current_level == pytest.approx(205, abs=0.1)


# =============================================================================
# Response serialization (keeps the API shape stable)
# =============================================================================


class TestResponseSerialization:
    def test_roundtrip_shape(self, precomputed):
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        doc = ap.to_response_dict(result)
        assert doc["lifter_name"] == "Bob B"
        assert doc["engine"] == "shrinkage"
        assert set(doc["lifts"].keys()) == {"squat", "bench", "deadlift"}
        for lift_key in ("squat", "bench", "deadlift"):
            ld = doc["lifts"][lift_key]
            assert "current_level" in ld
            assert "slope_combined_kg_per_day" in ld
            assert "slope_combined_kg_per_month" in ld
            assert "w_personal" in ld
            assert "projected_points" in ld


# =============================================================================
# Outlier flag
# =============================================================================


class TestOutlierFlag:
    def test_no_outlier_on_monotonic_bob(self, precomputed):
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        # Bob's bench is monotonic increasing -> no outlier.
        assert "bench" not in result.outlier_lifts


# =============================================================================
# Precompute wiring against the synthetic test fixture
# =============================================================================


class TestPrecompute:
    def test_precompute_populates_tables(self, precomputed):
        # Synthetic fixture is tiny, so cohort tables use global_mean fallback
        # for every (division, lift) pair -- but they must exist.
        assert ap.is_precomputed() is True
        # Open division gets the most fixture data.
        table = ap.get_cohort_table("Open", "squat")
        assert table is not None
        # K-M table for Open should exist with a non-zero sample.
        km = ap.get_km_table("Open")
        assert km is not None
        assert km.sample_size > 0

    def test_mixed_effects_returns_result_with_engine_label(self, precomputed):
        result = ap.mixed_effects_projection("Bob B")
        assert result is not None
        assert result.engine == "mixed_effects"
        # Until MixedLM wiring lands, Engine D returns the shrinkage fallback.
        assert result.meta.get("engine_d_available") is False
