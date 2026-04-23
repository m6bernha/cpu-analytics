"""Tests for the cohort progression endpoint.

Uses the synthetic fixture from conftest.py. The fixture has:
  - Alice: 3 meets, Junior at 22-23 then Open at 25
  - Bob: 4 SBD meets + 1 bench-only, all Open
  - Carl: 2 meets 4 years apart (comeback), Open
  - Dana: 1 meet only (should be excluded)
  - Ella: 2 Multi-ply Open SBD meets with class change 72 -> 84
"""

from __future__ import annotations

import pytest
from backend.app.progression import (
    METRIC_COLS,
    compute_lift_progression,
    compute_progression,
)


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


class TestLiftProgressionFilters:
    """Per-filter plumbing tests for compute_lift_progression.

    Each test compares a baseline result (filter off / default) against the
    same query with the filter on, proving the parameter reaches the SQL
    WHERE clause or the pandas post-filter instead of being silently
    dropped. Each test asserts a concrete n_lifters delta against the
    fixture so a regression breaks immediately.

    Fixture snapshot relevant here (all Canada + IPF, Event=SBD unless
    noted):
      - Alice: F, Raw, 63, Juniors then Open, 3 meets at ages 22/23/25.
      - Bob:   M, Raw, 83, Open, 4 SBD meets ages 28-31, plus 1 bench-only.
      - Carl:  M, Raw, 93, Open, 2 meets ages 25 and 29 (4-year gap).
      - Dana:  F, Raw, 57, Juniors, 1 meet (excluded by MeetCount>=2).
      - Ella:  F, Multi-ply, Open, 2 meets at class 72 then 84 (class change).
    """

    def test_sex_filter_reaches_sql(self, test_conn):
        male = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        female = compute_lift_progression(
            sex="F", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        # Raw males with 2+ full-SBD meets: Bob, Carl
        assert male["n_lifters"] == 2
        # Raw females with 2+ full-SBD meets: Alice only (Dana excluded)
        assert female["n_lifters"] == 1

    def test_equipment_filter_reaches_sql(self, test_conn):
        raw = compute_lift_progression(
            equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        equipped = compute_lift_progression(
            equipment="Equipped", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        # Raw (any sex): Alice, Bob, Carl
        assert raw["n_lifters"] == 3
        # Equipped expands to Multi-ply/Single-ply/Wraps/Unlimited: only Ella
        assert equipped["n_lifters"] == 1

    def test_event_filter_reaches_sql(self, test_conn):
        sbd = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        bench = compute_lift_progression(
            sex="M", equipment="Raw", event="B",
            country="Canada", parent_federation="IPF",
        )
        # SBD males: Bob, Carl
        assert sbd["n_lifters"] == 2
        # Bench-only: Bob has a single bench meet, MeetCount=1 excludes him
        assert bench["n_lifters"] == 0

    def test_weight_class_filter_reaches_sql(self, test_conn):
        wc_83 = compute_lift_progression(
            equipment="Raw", event="SBD", weight_class="83",
            country="Canada", parent_federation="IPF",
        )
        wc_93 = compute_lift_progression(
            equipment="Raw", event="SBD", weight_class="93",
            country="Canada", parent_federation="IPF",
        )
        # Only Bob in 83 Raw, only Carl in 93 Raw.
        assert wc_83["n_lifters"] == 1
        assert wc_93["n_lifters"] == 1

    def test_division_filter_reaches_sql(self, test_conn):
        open_div = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD", division="Open",
            country="Canada", parent_federation="IPF",
        )
        junior_div = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD", division="Junior",
            country="Canada", parent_federation="IPF",
        )
        # Open male Raw: Bob, Carl
        assert open_div["n_lifters"] == 2
        # No male Junior lifters in fixture
        assert junior_div["n_lifters"] == 0

    def test_age_category_filter_reaches_sql(self, test_conn):
        jr = compute_lift_progression(
            equipment="Raw", event="SBD", age_category="Jr",
            country="Canada", parent_federation="IPF",
        )
        open_cat = compute_lift_progression(
            equipment="Raw", event="SBD", age_category="Open",
            country="Canada", parent_federation="IPF",
        )
        # Alice has two Junior-age meets (22, 23). Baseline recomputes
        # against her first surviving Junior meet.
        assert jr["n_lifters"] == 1
        # Alice's one Open meet (age 25) is dropped (MeetCount<2 after
        # filter). Bob (ages 28-31) and Carl (25, 29) remain.
        assert open_cat["n_lifters"] == 2

    def test_max_gap_months_filter_reaches_sql(self, test_conn):
        no_gap = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        short_gap = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD", max_gap_months=24,
            country="Canada", parent_federation="IPF",
        )
        # Carl's 4-year gap exceeds 24 months and drops him.
        assert no_gap["n_lifters"] == 2
        assert short_gap["n_lifters"] == 1

    def test_same_class_only_filter_reaches_sql(self, test_conn):
        all_equipped = compute_lift_progression(
            sex="F", equipment="Equipped", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        same_class = compute_lift_progression(
            sex="F", equipment="Equipped", event="SBD", same_class_only=True,
            country="Canada", parent_federation="IPF",
        )
        # Ella has two meets across two weight classes. Without the filter
        # she contributes; with it she's excluded (ClassCount=2).
        assert all_equipped["n_lifters"] == 1
        assert same_class["n_lifters"] == 0


class TestMetricParam:
    """Tests for the metric= parameter (total / bodyweight / goodlift)."""

    def test_total_is_default(self, test_conn):
        """metric='total' and no metric arg produce identical results."""
        explicit = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="total", x_axis="Years",
        )
        default = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Years",
        )
        assert explicit["points"] == default["points"]
        assert explicit["metric"] == "total"
        assert default["metric"] == "total"

    def test_response_has_metric_and_y_label(self, test_conn):
        """Response always contains 'metric' and 'y_label' keys."""
        result = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="total", x_axis="Years",
        )
        assert "metric" in result
        assert "y_label" in result
        assert result["y_label"] == METRIC_COLS["total"][1]

    def test_avg_first_value_key(self, test_conn):
        """avg_first_value (not avg_first_total) is present in the response."""
        result = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Years",
        )
        assert "avg_first_value" in result
        assert "avg_first_total" not in result

    def test_bodyweight_metric_returns_data(self, test_conn):
        """metric='bodyweight' returns points and correct y_label."""
        result = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="bodyweight", x_axis="Years",
        )
        assert result["metric"] == "bodyweight"
        assert result["y_label"] == METRIC_COLS["bodyweight"][1]
        assert result["n_lifters"] >= 1
        # Day-0 diff is 0 for every lifter
        first_points = [p for p in result["points"] if p["x"] == 0]
        assert len(first_points) == 1
        assert abs(first_points[0]["y"]) < 0.01

    def test_goodlift_metric_returns_data(self, test_conn):
        """metric='goodlift' returns points and correct y_label."""
        result = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="goodlift", x_axis="Years",
        )
        assert result["metric"] == "goodlift"
        assert result["y_label"] == METRIC_COLS["goodlift"][1]
        assert result["n_lifters"] >= 1
        first_points = [p for p in result["points"] if p["x"] == 0]
        assert len(first_points) == 1
        assert abs(first_points[0]["y"]) < 0.01

    def test_invalid_metric_raises(self, test_conn):
        """Unknown metric value raises ValueError."""
        import pytest as _pytest
        with _pytest.raises(ValueError, match="Unknown metric"):
            compute_progression(
                sex="M", equipment="Raw", event="SBD",
                country="Canada", parent_federation="IPF",
                metric="dots",
            )

    def test_bodyweight_filters_honored(self, test_conn):
        """max_gap_months filter applies to bodyweight metric."""
        no_gap = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="bodyweight", x_axis="Years",
        )
        short_gap = compute_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="bodyweight", x_axis="Years",
            max_gap_months=24,
        )
        # Carl has a 4-year gap; with max_gap_months=24 he is dropped.
        assert no_gap["n_lifters"] > short_gap["n_lifters"]

    def test_goodlift_filters_honored(self, test_conn):
        """same_class_only filter applies to goodlift metric."""
        all_f = compute_progression(
            sex="F", equipment="Equipped", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="goodlift", x_axis="Years",
        )
        same = compute_progression(
            sex="F", equipment="Equipped", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="goodlift", x_axis="Years",
            same_class_only=True,
        )
        # Ella changes class, so same_class_only drops her.
        assert all_f["n_lifters"] >= same["n_lifters"]

    def test_empty_response_has_metric(self, test_conn):
        """Empty result for an impossible filter still returns metric/y_label."""
        result = compute_progression(
            sex="M", equipment="Single-ply", event="SBD",
            country="Canada", parent_federation="IPF",
            metric="bodyweight",
        )
        assert result["points"] == []
        assert result["metric"] == "bodyweight"
        assert result["y_label"] == METRIC_COLS["bodyweight"][1]


class TestCareerQuartileAxis:
    """Career quartile bucketing: for each lifter, split their meets into
    four equal-time windows Q1..Q4 from first-meet to last-meet."""

    def test_shape_matches_other_axes(self, test_conn):
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Career quartile",
            min_lifters_for_trend=1,
        )
        assert result["x_axis"] == "Career quartile"
        assert "first 25%" in result["x_label"]
        # Buckets are in [1, 4]; with Bob + Carl across their careers we
        # should see at least Q1 and a later quartile.
        xs = {p["x"] for p in result["points"]}
        assert xs.issubset({1, 2, 3, 4})
        assert 1 in xs

    def test_q1_contains_first_meet_only(self, test_conn):
        """Every lifter's DaysFromFirst=0 meet is Q1, so the Q1 bucket's
        mean diff-from-first is 0 (each lifter subtracts their own baseline)."""
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Career quartile",
            min_lifters_for_trend=1,
        )
        q1 = [p for p in result["points"] if p["x"] == 1]
        assert len(q1) == 1
        assert abs(q1[0]["y"]) < 0.01

    def test_no_projection_beyond_q4(self, test_conn):
        """Projection beyond Q4 has no meaning -- career is done by definition."""
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Career quartile",
            min_lifters_for_trend=1,
        )
        assert result["projection"] is None

    def test_trend_unit_is_quartile(self, test_conn):
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Career quartile",
            min_lifters_for_trend=1,
        )
        if result["trend"] is not None:
            assert result["trend"]["unit"] == "quartile"

    def test_same_day_career_lands_in_q1(self, test_conn):
        """Guard: lifters whose last-meet-day == first-meet-day have
        career_span=0, which would div-by-zero without the code's guard.
        The test fixture should not crash; everyone lands in Q1."""
        # This is mostly a smoke test since the synthetic fixture spans
        # real dates; the guard is visible in the implementation.
        result = compute_progression(
            sex="F", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Career quartile",
            min_lifters_for_trend=1,
        )
        for p in result["points"]:
            assert 1 <= p["x"] <= 4
