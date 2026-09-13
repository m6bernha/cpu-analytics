"""Branch tests for the two pure helpers extracted from Engine C's
``_project_single_lift`` on 2026-09-11 (``_blend_slopes`` and
``_pi_variance_at``). The extraction itself was gated by a byte-identical
backtest artifact before and after; these lock each branch so a later edit
to one helper cannot silently change the projection math.
"""
from __future__ import annotations

import math

import pytest

from backend.app.athlete_projection_engine_c import _blend_slopes, _pi_variance_at


class TestBlendSlopes:
    def test_both_present_is_weighted_mean(self):
        assert _blend_slopes(0.10, 0.02, 0.75) == pytest.approx(0.75 * 0.10 + 0.25 * 0.02)

    def test_weight_one_is_pure_personal_and_zero_is_pure_cohort(self):
        assert _blend_slopes(0.10, 0.02, 1.0) == pytest.approx(0.10)
        assert _blend_slopes(0.10, 0.02, 0.0) == pytest.approx(0.02)

    def test_missing_cohort_falls_back_to_personal(self):
        assert _blend_slopes(0.10, None, 0.3) == 0.10

    def test_missing_personal_falls_back_to_cohort(self):
        assert _blend_slopes(None, 0.02, 0.3) == 0.02

    def test_neither_is_none(self):
        assert _blend_slopes(None, None, 0.5) is None


def _base(**over):
    kw = dict(
        n_meets=8, slope_personal=0.05, sigma_personal=10.0, s_xx=200_000.0,
        t_mean_days=400.0, seg_slope_cohort=0.02, seg_sigma_cohort=0.001,
        km_multiplier=1.2, w_personal=0.8, sigma_resid=10.0,
    )
    kw.update(over)
    return kw


class TestPiVarianceAt:
    def test_both_sources_combine_by_squared_weights(self):
        kw = _base()
        var = _pi_variance_at(900.0, 300.0, **kw)
        var_personal = 10.0 ** 2 * (1 + 1 / 8 + (900.0 - 400.0) ** 2 / 200_000.0)
        var_cohort = (0.001 * 1.2 * 300.0) ** 2
        assert var == pytest.approx(0.8 ** 2 * var_personal + 0.2 ** 2 * var_cohort)

    def test_personal_term_uses_raw_day_and_cohort_term_uses_effective_offset(self):
        # Same next_day, different damped offset: only the cohort term moves.
        kw = _base()
        a = _pi_variance_at(900.0, 300.0, **kw)
        b = _pi_variance_at(900.0, 150.0, **kw)
        var_cohort_a = (0.001 * 1.2 * 300.0) ** 2
        var_cohort_b = (0.001 * 1.2 * 150.0) ** 2
        assert a - b == pytest.approx(0.2 ** 2 * (var_cohort_a - var_cohort_b))

    def test_no_personal_slope_means_pure_cohort_variance(self):
        kw = _base(slope_personal=None, sigma_personal=None, s_xx=None, w_personal=0.0)
        var = _pi_variance_at(900.0, 300.0, **kw)
        assert var == pytest.approx((0.001 * 1.2 * 300.0) ** 2)

    def test_no_cohort_cell_means_pure_personal_variance(self):
        kw = _base(seg_slope_cohort=None, seg_sigma_cohort=0.0)
        var = _pi_variance_at(900.0, 300.0, **kw)
        var_personal = 10.0 ** 2 * (1 + 1 / 8 + (900.0 - 400.0) ** 2 / 200_000.0)
        assert var == pytest.approx(var_personal)

    def test_single_meet_has_no_personal_variance_even_with_a_slope(self):
        # n_meets < 2 (or s_xx = 0) zeroes the personal term; the cohort
        # weight still applies with w_personal = n/(n+K).
        kw = _base(n_meets=1, s_xx=0.0, w_personal=0.1)
        var = _pi_variance_at(900.0, 300.0, **kw)
        assert var == pytest.approx(0.9 ** 2 * (0.001 * 1.2 * 300.0) ** 2)

    def test_no_data_at_all_gives_neutral_band_from_sigma_resid(self):
        kw = _base(slope_personal=None, sigma_personal=None, s_xx=None,
                   seg_slope_cohort=None, seg_sigma_cohort=0.0, w_personal=0.0,
                   sigma_resid=7.5)
        assert _pi_variance_at(900.0, 300.0, **kw) == pytest.approx(7.5 ** 2)

    def test_variance_is_never_negative(self):
        kw = _base(sigma_personal=0.0, seg_sigma_cohort=0.0, sigma_resid=0.0)
        v = _pi_variance_at(900.0, 300.0, **kw)
        assert v >= 0.0 and math.isfinite(v)
