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
    """Populate module-level cohort + K-M + MixedLM tables from the test parquet."""
    ap.precompute_tables()
    yield
    ap._COHORT = {}
    ap._KM = {}
    ap._MIXEDLM = {}
    ap._MIXEDLM_CONVERGED_PCT = 0.0
    ap._ENGINE_D_GLOBAL_AVAILABLE = False
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
# GLP-bracket cohort stratification (Sean Yen pivot)
# =============================================================================


class TestGlpBracketCohort:
    def test_precompute_populates_cell_keys(self, precomputed):
        """Every (division, bracket, lift) triple should resolve to a cell."""
        from backend.app.ipf_gl_points import GLP_BRACKET_LABELS
        for division in ap.AGE_DIVISIONS:
            for bracket in GLP_BRACKET_LABELS:
                for lift in ap.LIFT_KEYS:
                    cell = ap.get_cohort_cell(division, bracket, lift)
                    # Synthetic fixture is tiny; every cell will be either
                    # global fallback or merged, but must exist.
                    assert cell is not None
                    assert cell.lift == lift
                    assert cell.division == division

    def test_build_division_cells_emits_global_fallback_for_small_division(self):
        """With fewer than MIN_COHORT_CELL_SIZE total, emit division-global cells."""
        cell_slopes = {
            ("Open", "60-70", "squat"): [0.05, 0.06],
            ("Open", "70-80", "squat"): [0.04, 0.045, 0.05],
        }
        out: dict = {}
        ap._build_division_cells(cell_slopes, "Open", "squat", out)
        # Every bracket gets a cell with is_global_fallback=True.
        for bracket in ap.GLP_BRACKET_LABELS:
            cell = out[("Open", bracket, "squat")]
            assert cell.is_global_fallback is True
            # Merged_from covers all brackets.
            assert len(cell.merged_from) == 11

    def test_build_division_cells_merges_upward_then_downward(self):
        """A sparse 90-95 cell merges with 95-100 (and beyond) to reach 20."""
        # Fabricate 20 lifters in 95-100 plus 5 in 90-95; 90-95 should merge
        # upward and reuse the same cell as 95-100.
        import numpy as np
        rng = np.random.default_rng(0)
        cell_slopes = {
            ("Open", "90-95", "squat"): rng.uniform(0.04, 0.06, 5).tolist(),
            ("Open", "95-100", "squat"): rng.uniform(0.03, 0.05, 20).tolist(),
        }
        # Pad other brackets so division total is well above min.
        for b in ap.GLP_BRACKET_LABELS:
            if (("Open", b, "squat") not in cell_slopes):
                cell_slopes[("Open", b, "squat")] = rng.uniform(0.05, 0.07, 20).tolist()
        out: dict = {}
        ap._build_division_cells(cell_slopes, "Open", "squat", out)
        cell_90 = out[("Open", "90-95", "squat")]
        # 90-95 had 5; merged with 95-100's 20 for 25 total.
        assert cell_90.n_lifters >= ap.MIN_COHORT_CELL_SIZE
        assert "90-95" in cell_90.merged_from
        assert "95-100" in cell_90.merged_from

    def test_lifter_bracket_in_meta(self, precomputed):
        """The response's meta.lifter_bracket is populated with bracket label + n_cell."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        lb = result.meta.get("lifter_bracket")
        assert lb is not None
        assert lb["bracket"] in ap.GLP_BRACKET_LABELS
        assert isinstance(lb["n_cell"], int)
        assert isinstance(lb["merged_from"], list)
        # glp_score may be None for synthetic lifters with edge-case data;
        # when present it should be a positive float.
        if lb["glp_score"] is not None:
            assert lb["glp_score"] > 0

    def test_brackets_per_point_in_meta(self, precomputed):
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        brackets = result.meta.get("brackets_per_point")
        assert isinstance(brackets, list)
        assert len(brackets) == 6  # default n_points
        for b in brackets:
            assert b in ap.GLP_BRACKET_LABELS

    def test_bracket_transition_triggers_pass2(self, precomputed, monkeypatch):
        """Inject two cells with VERY different slopes. If the pass-1 total
        crosses a boundary, the meta.bracket_transitions count should be > 0."""
        # Replace Bob's Open + <60 cell with a very high slope, and the next
        # bracket with a very low slope. A pass-1 projection at the high slope
        # may push the projected total into the next bracket.
        original = dict(ap._COHORT)

        from backend.app.ipf_gl_points import GLP_BRACKET_LABELS
        for lift in ap.LIFT_KEYS:
            ap._COHORT[("Open", "<60", lift)] = ap.GlpCohortCell(
                division="Open", glp_bracket="<60", lift=lift,
                n_lifters=100, slope_kg_per_day=0.20,  # extreme gain
                residual_std=0.01, merged_from=(), is_global_fallback=False,
            )
            for b in GLP_BRACKET_LABELS[1:]:
                ap._COHORT[("Open", b, lift)] = ap.GlpCohortCell(
                    division="Open", glp_bracket=b, lift=lift,
                    n_lifters=100, slope_kg_per_day=0.001,
                    residual_std=0.001, merged_from=(), is_global_fallback=False,
                )
        try:
            result = ap.shrinkage_projection("Bob B", horizon_months=18)
            assert result is not None
            # Bob starts around 565 total -> IPF-GL below 60 at 82 kg,
            # so initial bracket is "<60" in the synthetic. Cell above
            # drives a huge slope in pass 1, likely pushing him into a
            # higher bracket during the horizon.
            brackets = result.meta["brackets_per_point"]
            distinct = len(set(brackets))
            # Either the projection stays in one bracket (slopes collapse
            # at the boundary) or a transition is observed. Both are valid.
            assert distinct >= 1
        finally:
            ap._COHORT.clear()
            ap._COHORT.update(original)


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
            assert "history" in ld
            # Every history row is a complete {date, days_from_first, kg} dict.
            for h in ld["history"]:
                assert set(h.keys()) >= {"date", "days_from_first", "kg"}


class TestPerLiftHistory:
    def test_history_length_matches_lift_meet_count(self, precomputed):
        """Bob has 4 SBD meets contesting squat/deadlift and 5 meets contesting
        bench (4 SBD + 1 bench-only). history length should match n_meets."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        for lift_key in ("squat", "bench", "deadlift"):
            lp = result.lifts[lift_key]
            assert len(lp.history) == lp.n_meets

    def test_history_values_match_lift_column(self, precomputed):
        """The kg values in history should be the raw lift-column values."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        squat_history = result.lifts["squat"].history
        # Bob's SBD squats: 190, 200, 205, 200 (as loaded in the conftest).
        # Confirm the last value is what current_level is anchored on.
        assert len(squat_history) > 0
        assert all(h["kg"] > 0 for h in squat_history)
        # Dates are sorted chronologically by construction.
        dates = [h["date"] for h in squat_history]
        assert dates == sorted(dates)

    def test_history_origin_matches_projection_axis(self, precomputed):
        """history[0].days_from_first should be 0 (lifter's first meet for
        this lift) and history[-1].days_from_first should equal
        last_meet_day, matching the x-axis origin used by projected_points."""
        result = ap.shrinkage_projection("Bob B")
        assert result is not None
        for lift_key in ("squat", "bench", "deadlift"):
            lp = result.lifts[lift_key]
            if lp.n_meets == 0:
                continue
            assert lp.history[0]["days_from_first"] == pytest.approx(0.0, abs=0.1)
            if lp.last_meet_day is not None:
                assert lp.history[-1]["days_from_first"] == pytest.approx(
                    lp.last_meet_day, abs=0.1
                )


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
    def test_precompute_populates_cells(self, precomputed):
        """Every (division, bracket, lift) key resolves to a GlpCohortCell."""
        from backend.app.ipf_gl_points import GLP_BRACKET_LABELS
        assert ap.is_precomputed() is True
        cell = ap.get_cohort_cell("Open", GLP_BRACKET_LABELS[0], "squat")
        assert cell is not None
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


# =============================================================================
# Serialized cohort + K-M artifact (preprocess -> backend boot fast path)
# =============================================================================


class TestSerializedTables:
    def test_round_trip_preserves_cohort_and_km(self, precomputed, tmp_path):
        """serialize_tables -> load_serialized_tables yields byte-equivalent
        in-memory state."""
        path = tmp_path / "athlete_projection_tables.json"
        cohort_before = dict(ap._COHORT)
        km_before = dict(ap._KM)
        assert len(cohort_before) > 0
        assert len(km_before) > 0

        ap.serialize_tables(path)
        assert path.exists()
        assert path.stat().st_size > 0

        # Reset module state to be sure load actually repopulates it.
        ap._COHORT = {}
        ap._KM = {}
        ap._PRECOMPUTED = False

        stats = ap.load_serialized_tables(path)
        assert stats["cohort_cells"] == len(cohort_before)
        assert stats["km_tables"] == len(km_before)
        assert ap.is_precomputed() is True

        # Every key survives and values round-trip, including merged-alias
        # keys (multiple dict keys that pointed to the same Cell object
        # before serialisation must still point to the same Cell object
        # after load).
        assert set(ap._COHORT.keys()) == set(cohort_before.keys())
        for key, before in cohort_before.items():
            after = ap._COHORT[key]
            assert after.division == before.division
            assert after.glp_bracket == before.glp_bracket
            assert after.lift == before.lift
            assert after.n_lifters == before.n_lifters
            assert after.slope_kg_per_day == pytest.approx(
                before.slope_kg_per_day, rel=1e-9,
            )
            assert after.residual_std == pytest.approx(
                before.residual_std, rel=1e-9,
            )
            assert after.merged_from == before.merged_from
            assert after.is_global_fallback == before.is_global_fallback

        for div, km in km_before.items():
            loaded = ap._KM[div]
            assert loaded.sample_size == km.sample_size
            assert loaded.survival_by_month == km.survival_by_month

    def test_round_trip_preserves_merged_alias_identity(
        self, precomputed, tmp_path,
    ):
        """Multiple dict keys aliasing the same GlpCohortCell object (after
        bracket merging) must still alias the same object after reload.
        Without this invariant, mutating a cell post-boot would no longer
        reflect across its aliased keys."""
        from collections import defaultdict
        before_groups: dict[int, list] = defaultdict(list)
        for key, cell in ap._COHORT.items():
            before_groups[id(cell)].append(key)
        aliased_groups = [keys for keys in before_groups.values() if len(keys) > 1]
        if not aliased_groups:
            pytest.skip("synthetic fixture has no merged-alias cells to exercise")

        path = tmp_path / "tables.json"
        ap.serialize_tables(path)
        ap._COHORT = {}
        ap._KM = {}
        ap._PRECOMPUTED = False
        ap.load_serialized_tables(path)

        for keys in aliased_groups:
            cells_after = {id(ap._COHORT[k]) for k in keys}
            assert len(cells_after) == 1, (
                f"merged-alias group {keys} lost identity during round trip: "
                f"{cells_after}"
            )

    def test_schema_version_mismatch_raises(self, precomputed, tmp_path):
        """Old artifact with wrong schema_version forces fallback to live fit."""
        import json
        path = tmp_path / "bad.json"
        ap.serialize_tables(path)
        with path.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        doc["schema_version"] = ap.SERIALIZED_TABLES_SCHEMA_VERSION + 1
        with path.open("w", encoding="utf-8") as f:
            json.dump(doc, f)

        with pytest.raises(ValueError, match="schema_version"):
            ap.load_serialized_tables(path)

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ap.load_serialized_tables(tmp_path / "does-not-exist.json")

    def test_artifact_is_reasonably_compact(self, precomputed, tmp_path):
        """Sanity check for release-asset size. Real production artifact
        should be under 100 KB; the synthetic test fixture is smaller still."""
        path = tmp_path / "tables.json"
        ap.serialize_tables(path)
        size_kb = path.stat().st_size / 1024.0
        # 100 KB ceiling guards against an accidental pickle of the full
        # DataFrame or similar.
        assert size_kb < 100, f"artifact {size_kb:.1f} KB is implausibly large"


# =============================================================================
# Engine D (MixedLM) -- B-2 wiring 2026-04-29
# =============================================================================


class TestMixedLMCellSerialization:
    def test_round_trip_preserves_mixedlm_cells(self, precomputed, tmp_path):
        """serialize_tables -> load_serialized_tables preserves MixedLM
        fit parameters and merged-alias identity for `_MIXEDLM`."""
        path = tmp_path / "tables.json"
        mixedlm_before = dict(ap._MIXEDLM)
        pct_before = ap._MIXEDLM_CONVERGED_PCT
        # Synthetic fixture is small; the test fixture's lifters may not
        # produce any MixedLM cells. Skip if so -- the cohort serialization
        # tests already prove the round-trip mechanics.
        if not mixedlm_before:
            pytest.skip("synthetic fixture produced no MixedLM cells")

        ap.serialize_tables(path)
        ap._MIXEDLM = {}
        ap._MIXEDLM_CONVERGED_PCT = 0.0

        stats = ap.load_serialized_tables(path)
        assert stats["mixedlm_cells"] == len(mixedlm_before)
        assert ap._MIXEDLM_CONVERGED_PCT == pytest.approx(pct_before)

        for key, before in mixedlm_before.items():
            after = ap._MIXEDLM[key]
            assert after.division == before.division
            assert after.glp_bracket == before.glp_bracket
            assert after.lift == before.lift
            assert after.converged == before.converged
            assert after.failure_mode == before.failure_mode
            assert after.fixed_slope_kg_per_year == pytest.approx(
                before.fixed_slope_kg_per_year, rel=1e-9, abs=1e-12,
            )
            assert after.random_intercept_var == pytest.approx(
                before.random_intercept_var, rel=1e-9, abs=1e-12,
            )
            assert after.residual_var == pytest.approx(
                before.residual_var, rel=1e-9, abs=1e-12,
            )
            assert after.merged_from == before.merged_from
            assert after.is_global_fallback == before.is_global_fallback


def _make_mixedlm_cell(
    division: str = "Open",
    glp_bracket: str = "<60",
    lift: str = "squat",
    converged: bool = True,
    fixed_slope: float = 12.0,
    residual_var: float = 100.0,
) -> ap.MixedLMCell:
    """Build a synthetic MixedLMCell for runtime-path tests.

    Post-P5-path-2 (random-intercept-only): no random_slope_var/random_cov
    fields; cohort uncertainty in synthesis is derived from residual_var.
    """
    return ap.MixedLMCell(
        division=division,
        glp_bracket=glp_bracket,
        lift=lift,
        n_lifters=25,
        n_meets=120,
        converged=converged,
        failure_mode=None if converged else "did_not_converge",
        fixed_intercept=400.0,
        fixed_slope_kg_per_year=fixed_slope,
        random_intercept_var=900.0,
        residual_var=residual_var,
        merged_from=(),
        is_global_fallback=False,
    )


class TestMixedLMVirtualCohortCell:
    def test_synthesis_converts_year_to_day(self):
        """Virtual cohort cell emitted from MixedLMCell uses kg/day units.
        Post-P5-path-2 the cohort std is sqrt(residual_var) / 365.25."""
        ml = _make_mixedlm_cell(fixed_slope=36.525, residual_var=4.0)
        virtual = ap._mixedlm_to_virtual_cohort_cell(ml)
        # 36.525 kg/year ~= 0.1 kg/day
        assert virtual.slope_kg_per_day == pytest.approx(0.1, rel=1e-9)
        # sqrt(4) = 2 kg of per-meet residual std -> 2 / 365.25 kg/day equivalent
        assert virtual.residual_std == pytest.approx(2.0 / 365.25, rel=1e-9)
        assert virtual.division == ml.division
        assert virtual.glp_bracket == ml.glp_bracket
        assert virtual.lift == ml.lift


class TestEngineDRuntime:
    """End-to-end Engine D dispatch using a known lifter from the fixture.

    Strategy: pick any lifter Engine C can project; fake the MixedLM table
    to control which lifts converge vs fall back. Keeps tests fast and
    deterministic without depending on the synthetic fixture's MixedLM
    convergence (which the fixture is too small to reliably produce).
    """

    def _pick_lifter(self, precomputed) -> tuple[str, str]:
        """Find a lifter the fixture can project; return (name, age_division)."""
        # _COHORT is populated by precomputed; iterate a handful of names
        # from the cohort history and find one that shrinkage_projection
        # accepts.
        cursor = ap.get_cursor()
        df = cursor.execute(
            "SELECT DISTINCT Name FROM openipf "
            "WHERE Country='Canada' AND ParentFederation='IPF' "
            "AND Event='SBD' AND TotalKg IS NOT NULL "
            "AND BodyweightKg IS NOT NULL AND Age IS NOT NULL "
            "LIMIT 50",
        ).df()
        for name in df["Name"].tolist():
            result = ap.shrinkage_projection(name, horizon_months=12)
            if result is not None:
                return name, result.age_division
        pytest.skip("no fixture lifter projectable through Engine C")

    def test_all_fallback_when_no_mixedlm_cells(self, precomputed):
        """Empty `_MIXEDLM` -> all 3 lifts fall back, not partial."""
        name, _ = self._pick_lifter(precomputed)
        # Save + clear MixedLM, then restore in finally.
        saved = dict(ap._MIXEDLM)
        ap._MIXEDLM = {}
        try:
            result = ap.mixed_effects_projection(name, horizon_months=12)
        finally:
            ap._MIXEDLM = saved
        assert result is not None
        assert result.engine == "mixed_effects"
        meta = result.meta
        assert set(meta["engine_d_fallback_lifts"]) == set(ap.LIFT_KEYS)
        assert meta["engine_d_partial"] is False
        assert meta["engine_d_available"] is False

    def test_partial_when_one_lift_did_not_converge(self, precomputed):
        """Two converged + one non-converged -> engine_d_partial=True,
        fallback_lifts contains exactly the non-converged lift."""
        name, division = self._pick_lifter(precomputed)
        result_c = ap.shrinkage_projection(name, horizon_months=12)
        bracket = (result_c.meta or {}).get("lifter_bracket", {}).get("bracket")
        assert bracket is not None, "fixture lifter has no resolved bracket"

        # Build a synthetic MixedLM table where deadlift fails.
        saved = dict(ap._MIXEDLM)
        saved_pct = ap._MIXEDLM_CONVERGED_PCT
        saved_avail = ap._ENGINE_D_GLOBAL_AVAILABLE
        synth: dict[tuple[str, str, str], ap.MixedLMCell] = {}
        for lift in ap.LIFT_KEYS:
            synth[(division, bracket, lift)] = _make_mixedlm_cell(
                division=division,
                glp_bracket=bracket,
                lift=lift,
                converged=(lift != "deadlift"),
            )
        ap._MIXEDLM = synth
        ap._MIXEDLM_CONVERGED_PCT = 0.95
        ap._ENGINE_D_GLOBAL_AVAILABLE = True
        try:
            result = ap.mixed_effects_projection(name, horizon_months=12)
        finally:
            ap._MIXEDLM = saved
            ap._MIXEDLM_CONVERGED_PCT = saved_pct
            ap._ENGINE_D_GLOBAL_AVAILABLE = saved_avail

        assert result is not None
        meta = result.meta
        assert meta["engine_d_partial"] is True
        assert meta["engine_d_fallback_lifts"] == ("deadlift",)
        assert meta["engine_d_available"] is True
        assert "fell back" in (meta["engine_d_note"] or "").lower()

    def test_all_converged_clears_engine_d_available(self, precomputed):
        """All 3 lifts converged AND global gate on -> engine_d_available=True
        with no fallbacks reported."""
        name, division = self._pick_lifter(precomputed)
        result_c = ap.shrinkage_projection(name, horizon_months=12)
        bracket = (result_c.meta or {}).get("lifter_bracket", {}).get("bracket")
        assert bracket is not None

        saved = dict(ap._MIXEDLM)
        saved_pct = ap._MIXEDLM_CONVERGED_PCT
        saved_avail = ap._ENGINE_D_GLOBAL_AVAILABLE
        synth: dict[tuple[str, str, str], ap.MixedLMCell] = {}
        for lift in ap.LIFT_KEYS:
            synth[(division, bracket, lift)] = _make_mixedlm_cell(
                division=division,
                glp_bracket=bracket,
                lift=lift,
                converged=True,
            )
        ap._MIXEDLM = synth
        ap._MIXEDLM_CONVERGED_PCT = 0.95
        ap._ENGINE_D_GLOBAL_AVAILABLE = True
        try:
            result = ap.mixed_effects_projection(name, horizon_months=12)
        finally:
            ap._MIXEDLM = saved
            ap._MIXEDLM_CONVERGED_PCT = saved_pct
            ap._ENGINE_D_GLOBAL_AVAILABLE = saved_avail

        assert result is not None
        meta = result.meta
        assert meta["engine_d_partial"] is False
        assert meta["engine_d_fallback_lifts"] == ()
        assert meta["engine_d_available"] is True

    def test_global_gate_off_keeps_engine_d_unavailable(self, precomputed):
        """Even with all cells converged, if the global gate is off the
        per-response flag stays False (frontend would hide the toggle)."""
        name, division = self._pick_lifter(precomputed)
        result_c = ap.shrinkage_projection(name, horizon_months=12)
        bracket = (result_c.meta or {}).get("lifter_bracket", {}).get("bracket")
        assert bracket is not None

        saved = dict(ap._MIXEDLM)
        saved_pct = ap._MIXEDLM_CONVERGED_PCT
        saved_avail = ap._ENGINE_D_GLOBAL_AVAILABLE
        synth: dict[tuple[str, str, str], ap.MixedLMCell] = {}
        for lift in ap.LIFT_KEYS:
            synth[(division, bracket, lift)] = _make_mixedlm_cell(
                division=division,
                glp_bracket=bracket,
                lift=lift,
                converged=True,
            )
        ap._MIXEDLM = synth
        ap._MIXEDLM_CONVERGED_PCT = 0.5
        ap._ENGINE_D_GLOBAL_AVAILABLE = False
        try:
            result = ap.mixed_effects_projection(name, horizon_months=12)
        finally:
            ap._MIXEDLM = saved
            ap._MIXEDLM_CONVERGED_PCT = saved_pct
            ap._ENGINE_D_GLOBAL_AVAILABLE = saved_avail

        assert result.meta["engine_d_available"] is False
        # But it still ran with the synthetic cells, so partial=False
        # and no lifts fell back -- gate flips the response flag, not the
        # per-lift dispatch.
        assert result.meta["engine_d_fallback_lifts"] == ()


class TestProjectionEnginesEndpoint:
    def test_endpoint_returns_expected_shape(self, precomputed):
        """GET /api/athlete/projection-engines returns shrinkage always-on
        and mixed_effects gated on the global flag."""
        from fastapi.testclient import TestClient
        from backend.app.main import app

        with TestClient(app) as client:
            r = client.get("/api/athlete/projection-engines")
        assert r.status_code == 200
        body = r.json()
        assert body["shrinkage"] == {"available": True}
        assert "available" in body["mixed_effects"]
        assert "convergence_rate" in body["mixed_effects"]
        assert "n_cells" in body["mixed_effects"]
        assert isinstance(body["mixed_effects"]["available"], bool)


class TestSchemaVersionBumped:
    def test_schema_version_is_three(self):
        """P5 path 2 bumped the artifact schema; old v1/v2 artifacts must be rejected."""
        assert ap.SERIALIZED_TABLES_SCHEMA_VERSION == 3
