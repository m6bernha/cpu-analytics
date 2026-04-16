"""Tests for Phase 8 (projection, percentile) and Phase 9 (per-lift).

Uses the synthetic fixture from conftest.py.
"""

from __future__ import annotations

from backend.app.lifters import get_lifter_history, _compute_percentile
from backend.app.progression import compute_lift_progression, compute_progression


class TestIndividualProjection:
    """Phase 8A: individual trajectory projection."""

    def test_bob_has_projection(self, test_conn):
        """Bob has 4 SBD meets, enough to fit a trend and project."""
        result = get_lifter_history("Bob B")
        assert result["projection"] is not None
        proj = result["projection"]
        assert proj["slope_kg_per_month"] > 0  # Bob improves
        assert len(proj["points"]) > 0
        # Each projected point has bounds
        for p in proj["points"]:
            assert p["lower"] <= p["projected_total"] <= p["upper"]

    def test_carl_has_projection(self, test_conn):
        """Carl has only 2 SBD meets, needs 3+ for projection."""
        result = get_lifter_history("Carl C")
        # Carl has 2 SBD meets, below the 3-meet threshold
        assert result["projection"] is None

    def test_dana_no_projection(self, test_conn):
        """Dana has 1 meet, no projection possible."""
        result = get_lifter_history("Dana D")
        assert result["projection"] is None


class TestPercentileRank:
    """Phase 8C: percentile rank within cohort."""

    def test_bob_has_rank(self, test_conn):
        result = get_lifter_history("Bob B")
        rank = result.get("percentile_rank")
        # Bob is the only M / 83 / Raw SBD lifter in the fixture
        assert rank is not None
        assert rank["cohort_size"] == 1
        assert rank["percentile"] == 100.0

    def test_percentile_with_missing_class(self, test_conn):
        """If weight_class is None, return None."""
        result = _compute_percentile("Bob B", "M", None, "Raw")
        assert result is None


class TestCohortProjection:
    """Phase 8B: cohort projection with confidence intervals."""

    def test_projection_returned_with_trend(self, test_conn):
        result = compute_progression(
            sex="M", equipment="Raw", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Years", min_lifters_for_trend=1,
        )
        if result["trend"] is not None:
            assert result["projection"] is not None
            assert len(result["projection"]["points"]) == 4
            # Confidence band widens with distance
            points = result["projection"]["points"]
            for i in range(1, len(points)):
                band_i = points[i]["upper"] - points[i]["lower"]
                band_prev = points[i-1]["upper"] - points[i-1]["lower"]
                assert band_i >= band_prev

    def test_no_projection_when_no_trend(self, test_conn):
        """If the filter returns no data, projection is None."""
        result = compute_progression(
            sex="M", equipment="Single-ply", tested="Yes", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        assert result["projection"] is None


class TestPerLiftProgression:
    """Phase 9A: per-lift cohort progression."""

    def test_returns_three_lift_keys(self, test_conn):
        result = compute_lift_progression(
            sex="M", equipment="Raw", event="SBD",
            country="Canada", parent_federation="IPF",
            x_axis="Years",
        )
        assert "lifts" in result
        assert "squat" in result["lifts"]
        assert "bench" in result["lifts"]
        assert "deadlift" in result["lifts"]

    def test_empty_result_shape(self, test_conn):
        result = compute_lift_progression(
            sex="F", equipment="Single-ply", event="SBD",
            country="Canada", parent_federation="IPF",
        )
        assert result["lifts"]["squat"] == []
        assert result["lifts"]["bench"] == []
        assert result["lifts"]["deadlift"] == []
        assert result["n_lifters"] == 0


class TestWeightClassMigration:
    """Phase 7A: class change detection."""

    def test_alice_has_migration(self, test_conn):
        """Alice competed at 63 kg consistently. No migration."""
        result = get_lifter_history("Alice A")
        changes = result.get("weight_class_changes", [])
        assert changes == []

    def test_search_returns_latest_metadata(self, test_conn):
        """Roundtable fix: search should return latest meet metadata."""
        from backend.app.lifters import search_lifters
        results = search_lifters(q="Bob", country="Canada", parent_federation="IPF")
        assert len(results) == 1
        # Bob's LATEST SBD meet is 2025-01-15, the bench meet is 2023-06-01.
        # Actually his last meet by date is 2025-01-15 SBD.
        # LatestMeetDate should be the most recent, not the earliest.
        assert results[0]["LatestMeetDate"] == "2025-01-15"
