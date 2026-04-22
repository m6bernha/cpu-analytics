"""Tests for backend.app.ipf_gl_points.

IPF GL benchmark totals were verified against the published coefficients
with a hand calculation:

  Men, 750 kg total at 83 kg BW:
    denom = 1199.72839 - 1025.18162 * exp(-0.00921025 * 83)
          = 1199.72839 - 1025.18162 * 0.46569
          = 722.29
    GLP = 100 * 750 / 722.29 = 103.84

  Women, 400 kg total at 63 kg BW:
    denom = 610.32796 - 1045.59282 * exp(-0.03048 * 63)
          = 610.32796 - 1045.59282 * 0.14639
          = 457.25
    GLP = 100 * 400 / 457.25 = 87.48
"""

from __future__ import annotations

import math

import pytest

from backend.app.ipf_gl_points import (
    GLP_BRACKET_LABELS,
    assign_glp_bracket,
    ipf_gl_points,
)


class TestIpfGlPoints:
    def test_men_benchmark_total(self):
        """750 kg at 83 kg BW, elite-level Men's Open Raw -> GLP ~103.8."""
        glp = ipf_gl_points(total_kg=750.0, bw_kg=83.0, age=30.0, sex="M")
        assert glp is not None
        assert glp == pytest.approx(103.84, abs=0.1)

    def test_women_benchmark_total(self):
        """400 kg at 63 kg BW, elite-level Women's Open Raw -> GLP ~87.5."""
        glp = ipf_gl_points(total_kg=400.0, bw_kg=63.0, age=25.0, sex="F")
        assert glp is not None
        assert glp == pytest.approx(87.48, abs=0.1)

    def test_novice_glp_is_low(self):
        """Novice totals land well below 60."""
        glp = ipf_gl_points(total_kg=280.0, bw_kg=62.0, age=22.0, sex="F")
        assert glp is not None
        assert glp < 65  # novice/intermediate F at ~62 kg BW

    def test_case_insensitive_sex(self):
        a = ipf_gl_points(total_kg=500.0, bw_kg=83.0, age=30.0, sex="m")
        b = ipf_gl_points(total_kg=500.0, bw_kg=83.0, age=30.0, sex="M")
        assert a == b

    def test_returns_none_on_zero_bodyweight(self):
        assert ipf_gl_points(500.0, 0.0, 30.0, "M") is None

    def test_returns_none_on_negative_bodyweight(self):
        assert ipf_gl_points(500.0, -1.0, 30.0, "M") is None

    def test_returns_none_on_zero_total(self):
        assert ipf_gl_points(0.0, 83.0, 30.0, "M") is None

    def test_returns_none_on_invalid_sex(self):
        assert ipf_gl_points(500.0, 83.0, 30.0, "X") is None
        assert ipf_gl_points(500.0, 83.0, 30.0, "") is None

    def test_returns_none_on_nulls(self):
        assert ipf_gl_points(None, 83.0, 30.0, "M") is None
        assert ipf_gl_points(500.0, None, 30.0, "M") is None
        assert ipf_gl_points(500.0, 83.0, 30.0, None) is None

    def test_age_is_ignored(self):
        """IPF GL does not apply an age adjustment. Points are identical
        across ages for the same total+bw+sex."""
        young = ipf_gl_points(600.0, 83.0, 25.0, "M")
        masters = ipf_gl_points(600.0, 83.0, 55.0, "M")
        assert young is not None
        assert masters is not None
        assert young == masters

    def test_higher_total_gives_higher_glp(self):
        lower = ipf_gl_points(400.0, 83.0, 30.0, "M")
        higher = ipf_gl_points(600.0, 83.0, 30.0, "M")
        assert lower is not None and higher is not None
        assert higher > lower

    def test_lighter_bodyweight_gives_higher_glp_for_same_total(self):
        """IPF GL normalizes by bodyweight -- a smaller lifter scores higher
        for the same absolute total."""
        light = ipf_gl_points(500.0, 63.0, 30.0, "M")
        heavy = ipf_gl_points(500.0, 105.0, 30.0, "M")
        assert light is not None and heavy is not None
        assert light > heavy


class TestAssignGlpBracket:
    def test_low_glp_maps_to_under_60(self):
        assert assign_glp_bracket(45.0) == "<60"
        assert assign_glp_bracket(59.99) == "<60"

    def test_boundary_60_lands_in_60_70(self):
        assert assign_glp_bracket(60.0) == "60-70"

    def test_boundary_90_lands_in_90_95(self):
        assert assign_glp_bracket(90.0) == "90-95"

    def test_95_lands_in_95_100(self):
        assert assign_glp_bracket(95.0) == "95-100"

    def test_120_lands_in_top_bracket(self):
        assert assign_glp_bracket(120.0) == ">=120"

    def test_world_record_lands_in_top_bracket(self):
        assert assign_glp_bracket(145.0) == ">=120"

    def test_none_maps_to_lowest_bracket(self):
        assert assign_glp_bracket(None) == "<60"

    def test_zero_maps_to_lowest_bracket(self):
        assert assign_glp_bracket(0.0) == "<60"

    def test_nan_maps_to_lowest_bracket(self):
        assert assign_glp_bracket(float("nan")) == "<60"

    def test_inf_maps_to_lowest_bracket(self):
        assert assign_glp_bracket(math.inf) == "<60"

    def test_all_brackets_have_labels(self):
        assert len(GLP_BRACKET_LABELS) == 11
        expected = {"<60", "60-70", "70-80", "80-90", "90-95", "95-100",
                    "100-105", "105-110", "110-115", "115-120", ">=120"}
        assert set(GLP_BRACKET_LABELS) == expected
