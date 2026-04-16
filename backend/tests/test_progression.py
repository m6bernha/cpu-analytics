"""Tests for the cohort progression endpoint.

Uses the synthetic fixture from conftest.py. The fixture has:
  - Alice: 3 meets, Junior at 22-23 then Open at 25
  - Bob: 4 SBD meets + 1 bench-only, all Open
  - Carl: 2 meets 4 years apart (comeback), Open
  - Dana: 1 meet only (should be excluded)
"""

from __future__ import annotations

import pytest
from backend.app.progression import compute_progression


class TestBasicProgression:
    """Default filters, no age category."""

    def test_returns_correct_shape(self, test_conn):
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Years",
        )
        assert "points" in result
        assert "trend" in result
        assert "n_lifters" in result
        assert "n_meets" in result
        assert result["x_axis"] == "Years"
        assert result["x_label"] == "Years since first meet"

    def test_excludes_single_meet_lifters(self, test_conn):
        """Dana has 1 meet. She should not appear."""
        result = compute_progression(
            sex="F", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Days",
        )
        # Only Alice qualifies (3 meets, female, 2+ meets)
        assert result["n_lifters"] == 1
        names_in_data = set()
        # The response doesn't expose names, but n_lifters == 1 confirms Dana is excluded

    def test_first_point_is_zero(self, test_conn):
        """At x=0 (first meet), TotalDiffFromFirst should be ~0."""
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Days",
        )
        first_points = [p for p in result["points"] if p["x"] == 0]
        assert len(first_points) == 1
        # Mean diff at day 0 should be 0 (every lifter's baseline)
        assert abs(first_points[0]["y"]) < 0.01

    def test_empty_result_shape(self, test_conn):
        """A filter that matches nothing returns the empty shape."""
        result = compute_progression(
            sex="M", equipment="Single-ply", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        assert result["points"] == []
        assert result["trend"] is None
        assert result["n_lifters"] == 0
        assert result["n_meets"] == 0

    def test_trend_is_positive_for_male_cohort(self, test_conn):
        """Bob and Carl both improve over time.

        The synthetic dataset is small, so we lower min_lifters_for_trend
        to 1 to get a trendline. Production default is 5.
        """
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Years",
            min_lifters_for_trend=1,
        )
        assert result["trend"] is not None
        assert result["trend"]["slope"] > 0
        assert result["trend"]["unit"] == "year"


class TestAgeCategoryBaseline:
    """Regression tests for the age_category baseline fix (Phase 1A).

    Alice competes as Junior (age 22, 23) then Open (age 25).
    Her Junior totals are 280, 305. Her Open total is 330.

    BUG (before fix): with age_category=Open, Alice's diff was computed
    against her all-time first meet (280, Junior). So her Open delta
    showed +50 (330-280) anchored to an invisible baseline.

    CORRECT: with age_category=Open, Alice has only 1 meet in Open (330).
    Since MeetCount < 2 in the Open category, she should be excluded.
    Only Bob and Carl survive (both have 2+ Open meets).
    """

    def test_open_excludes_alice(self, test_conn):
        """Alice has only 1 Open meet, so she should be excluded."""
        result = compute_progression(
            sex=None, equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            age_category="Open",
            x_axis="Days",
        )
        # Bob has 4 Open meets, Carl has 2. Alice has 1 (excluded).
        assert result["n_lifters"] == 2

    def test_open_baseline_is_first_open_meet(self, test_conn):
        """Bob's first Open meet total is 500. His day-0 diff should be 0."""
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            age_category="Open",
            x_axis="Days",
        )
        first_points = [p for p in result["points"] if p["x"] == 0]
        assert len(first_points) == 1
        # At day 0, every surviving lifter's diff from their own first
        # Open meet should be 0, so the mean is 0.
        assert abs(first_points[0]["y"]) < 0.01

    def test_junior_includes_alice(self, test_conn):
        """Alice has 2 Junior meets (ages 22, 23). She should be included."""
        result = compute_progression(
            sex=None, equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            age_category="Jr",
            x_axis="Days",
        )
        # Only Alice has Junior meets with 2+ in category
        assert result["n_lifters"] == 1

    def test_junior_baseline_is_first_junior_meet(self, test_conn):
        """Alice's first Junior total is 280. Her diff at day 0 is 0."""
        result = compute_progression(
            sex=None, equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            age_category="Jr",
            x_axis="Days",
        )
        first_points = [p for p in result["points"] if p["x"] == 0]
        assert len(first_points) == 1
        assert abs(first_points[0]["y"]) < 0.01

    def test_junior_diff_is_correct(self, test_conn):
        """Alice: Junior meet 2 total is 305, meet 1 is 280. Diff = 25."""
        result = compute_progression(
            sex=None, equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            age_category="Jr",
            x_axis="Days",
        )
        # Alice's 2nd Junior meet is ~365 days after the first
        non_zero = [p for p in result["points"] if p["x"] > 0]
        assert len(non_zero) >= 1
        # Her diff should be 25 (305 - 280)
        assert abs(non_zero[0]["y"] - 25.0) < 0.01


class TestDivisionFilter:
    """Test Division filter works correctly."""

    def test_division_open(self, test_conn):
        result = compute_progression(
            sex=None, equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            division="Open",
            x_axis="Days",
        )
        # Bob (4 Open), Carl (2 Open), Alice's 3rd meet (1 Open, excluded)
        assert result["n_lifters"] == 2

    def test_division_all(self, test_conn):
        """Division='All' should not filter."""
        result = compute_progression(
            sex=None, equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            division="All",
            x_axis="Days",
        )
        # Alice (3), Bob (4), Carl (2) = 3 lifters
        assert result["n_lifters"] == 3
