"""Tests for manual trajectory computation."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.manual import (
    ManualMeetEntry,
    ManualTrajectoryRequest,
    build_manual_trajectory,
)


class TestBuildManualTrajectory:
    def test_empty_entries(self):
        req = ManualTrajectoryRequest(name="Test", sex="M", entries=[])
        result = build_manual_trajectory(req)
        assert result["meet_count"] == 0
        assert result["meets"] == []
        assert result["best_total_kg"] == 0.0

    def test_single_entry(self):
        req = ManualTrajectoryRequest(
            name="Test Lifter",
            sex="M",
            entries=[ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)],
        )
        result = build_manual_trajectory(req)
        assert result["meet_count"] == 1
        assert result["best_total_kg"] == 500.0
        assert result["meets"][0]["TotalDiffFromFirst"] == 0
        assert result["meets"][0]["DaysFromFirst"] == 0

    def test_multiple_entries_sorted(self):
        req = ManualTrajectoryRequest(
            name="Test",
            sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=550),
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 6, 1), total_kg=570),
            ],
        )
        result = build_manual_trajectory(req)
        # Should be sorted by date
        dates = [m["Date"] for m in result["meets"]]
        assert dates == sorted(dates)
        # First meet's diff is 0
        assert result["meets"][0]["TotalDiffFromFirst"] == 0
        # Second meet is 550 - 500 = 50
        assert result["meets"][1]["TotalDiffFromFirst"] == 50
        # Third is 570 - 500 = 70
        assert result["meets"][2]["TotalDiffFromFirst"] == 70

    def test_days_from_first(self):
        req = ManualTrajectoryRequest(
            name="Test",
            sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 1, 31), total_kg=510),
            ],
        )
        result = build_manual_trajectory(req)
        assert result["meets"][1]["DaysFromFirst"] == 30

    def test_optional_fields_preserved(self):
        req = ManualTrajectoryRequest(
            name="Test",
            sex="F",
            entries=[
                ManualMeetEntry(
                    date=date(2024, 1, 1),
                    total_kg=300,
                    weight_class="63",
                    squat_kg=110,
                    bench_kg=70,
                    deadlift_kg=120,
                    meet_name="Test Meet",
                ),
            ],
        )
        result = build_manual_trajectory(req)
        m = result["meets"][0]
        assert m["CanonicalWeightClass"] == "63"
        assert m["Best3SquatKg"] == 110
        assert m["Best3BenchKg"] == 70
        assert m["Best3DeadliftKg"] == 120
        assert m["MeetName"] == "Test Meet"


class TestTotalAndLiftsReconciliation:
    def test_total_only_preserves_old_behavior(self):
        entry = ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)
        assert entry.total_kg == 500
        assert entry.squat_kg is None
        assert entry.bench_kg is None
        assert entry.deadlift_kg is None

    def test_all_three_lifts_compute_total(self):
        entry = ManualMeetEntry(
            date=date(2024, 1, 1),
            squat_kg=180,
            bench_kg=120,
            deadlift_kg=210,
        )
        assert entry.total_kg == 510
        assert entry.squat_kg == 180

    def test_total_matching_lifts_accepted(self):
        entry = ManualMeetEntry(
            date=date(2024, 1, 1),
            total_kg=510,
            squat_kg=180,
            bench_kg=120,
            deadlift_kg=210,
        )
        assert entry.total_kg == 510

    def test_total_mismatching_lifts_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ManualMeetEntry(
                date=date(2024, 1, 1),
                total_kg=500,
                squat_kg=180,
                bench_kg=120,
                deadlift_kg=210,
            )
        msg = str(exc_info.value)
        assert "does not match" in msg

    def test_partial_lifts_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ManualMeetEntry(
                date=date(2024, 1, 1),
                total_kg=500,
                squat_kg=180,
                bench_kg=120,
            )
        msg = str(exc_info.value)
        assert "squat, bench, and deadlift" in msg

    def test_partial_lifts_without_total_rejected(self):
        with pytest.raises(ValidationError):
            ManualMeetEntry(date=date(2024, 1, 1), squat_kg=180)

    def test_no_total_no_lifts_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ManualMeetEntry(date=date(2024, 1, 1))
        msg = str(exc_info.value)
        assert "total" in msg.lower()

    def test_mixed_entries_total_only_and_lifts_only(self):
        req = ManualTrajectoryRequest(
            name="Test",
            sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(
                    date=date(2024, 4, 1),
                    squat_kg=190,
                    bench_kg=130,
                    deadlift_kg=220,
                ),
            ],
        )
        result = build_manual_trajectory(req)
        assert result["meet_count"] == 2
        first, second = result["meets"]
        assert first["TotalKg"] == 500
        assert first["Best3SquatKg"] is None
        assert second["TotalKg"] == 540
        assert second["Best3SquatKg"] == 190
        assert second["Best3BenchKg"] == 130
        assert second["Best3DeadliftKg"] == 220

    def test_fractional_lifts_compute_total(self):
        entry = ManualMeetEntry(
            date=date(2024, 1, 1),
            squat_kg=182.5,
            bench_kg=117.5,
            deadlift_kg=212.5,
        )
        assert entry.total_kg == 512.5


class TestMissingOptionalFields:
    def test_missing_individual_lifts_pass_through_as_none(self):
        """When only total is provided, individual lifts are None in output."""
        req = ManualTrajectoryRequest(
            name="Test", sex="M",
            entries=[ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)],
        )
        result = build_manual_trajectory(req)
        m = result["meets"][0]
        assert m["Best3SquatKg"] is None
        assert m["Best3BenchKg"] is None
        assert m["Best3DeadliftKg"] is None
        assert m["CanonicalWeightClass"] is None
        assert m["MeetName"] is None


class TestRateKgPerMonth:
    def test_single_entry_rate_is_none(self):
        """One meet means no slope: rate is None."""
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)],
        )
        assert build_manual_trajectory(req)["rate_kg_per_month"] is None

    def test_empty_entries_rate_is_none(self):
        req = ManualTrajectoryRequest(name="X", sex="M", entries=[])
        assert build_manual_trajectory(req)["rate_kg_per_month"] is None

    def test_same_day_entries_rate_is_none(self):
        """Two meets on the same date: days[-1] == days[0] guard trips."""
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=520),
            ],
        )
        assert build_manual_trajectory(req)["rate_kg_per_month"] is None

    def test_bench_only_rate_is_none(self):
        """Rate only computed for SBD, not bench-only events."""
        req = ManualTrajectoryRequest(
            name="X", sex="M", event="B",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=150),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=170),
            ],
        )
        assert build_manual_trajectory(req)["rate_kg_per_month"] is None

    def test_positive_slope_rate_close_to_expected(self):
        """60 days, +60 kg: 1 kg/day ~= 30.44 kg/month."""
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=560),
            ],
        )
        rate = build_manual_trajectory(req)["rate_kg_per_month"]
        assert rate is not None
        assert abs(rate - 30.44) < 0.1


class TestPrDetection:
    def test_sbd_first_meet_always_pr(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)],
        )
        assert build_manual_trajectory(req)["meets"][0]["is_pr"] is True

    def test_sbd_increasing_totals_all_pr(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520),
                ManualMeetEntry(date=date(2024, 6, 1), total_kg=540),
            ],
        )
        meets = build_manual_trajectory(req)["meets"]
        assert [m["is_pr"] for m in meets] == [True, True, True]

    def test_sbd_regression_flagged_not_pr(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520),
                ManualMeetEntry(date=date(2024, 6, 1), total_kg=510),
            ],
        )
        meets = build_manual_trajectory(req)["meets"]
        assert [m["is_pr"] for m in meets] == [True, True, False]

    def test_sbd_flat_equal_total_not_pr(self):
        """is_pr requires strictly greater, not >=."""
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=500),
            ],
        )
        meets = build_manual_trajectory(req)["meets"]
        assert meets[1]["is_pr"] is False

    def test_non_sbd_never_pr(self):
        """Bench-only: is_pr is False on every meet, regardless of totals."""
        req = ManualTrajectoryRequest(
            name="X", sex="M", event="B",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=150),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=170),
            ],
        )
        meets = build_manual_trajectory(req)["meets"]
        assert all(m["is_pr"] is False for m in meets)


class TestWeightClassChanges:
    def test_change_detected(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, weight_class="83"),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520, weight_class="93"),
            ],
        )
        changes = build_manual_trajectory(req)["weight_class_changes"]
        assert len(changes) == 1
        assert changes[0]["from_class"] == "83"
        assert changes[0]["to_class"] == "93"
        assert changes[0]["date"] == "2024-03-01"

    def test_constant_class_no_changes(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, weight_class="83"),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520, weight_class="83"),
            ],
        )
        assert build_manual_trajectory(req)["weight_class_changes"] == []

    def test_missing_class_not_flagged_as_change(self):
        """Entries with no weight_class don't trigger a change record."""
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, weight_class="83"),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520),
            ],
        )
        assert build_manual_trajectory(req)["weight_class_changes"] == []

    def test_multiple_changes_recorded(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, weight_class="83"),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520, weight_class="93"),
                ManualMeetEntry(date=date(2024, 6, 1), total_kg=530, weight_class="105"),
            ],
        )
        changes = build_manual_trajectory(req)["weight_class_changes"]
        assert len(changes) == 2
        assert changes[0]["to_class"] == "93"
        assert changes[1]["to_class"] == "105"


class TestProjectionDisabled:
    def test_projection_none_empty(self):
        req = ManualTrajectoryRequest(name="X", sex="M", entries=[])
        assert build_manual_trajectory(req)["projection"] is None

    def test_projection_none_single(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)],
        )
        assert build_manual_trajectory(req)["projection"] is None

    def test_projection_none_many(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, m, 1), total_kg=500 + m * 10)
                for m in range(1, 7)
            ],
        )
        assert build_manual_trajectory(req)["projection"] is None

    def test_percentile_rank_always_none(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520),
            ],
        )
        assert build_manual_trajectory(req)["percentile_rank"] is None


class TestSummaryFields:
    def test_best_total_is_max(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520),
                ManualMeetEntry(date=date(2024, 6, 1), total_kg=510),
            ],
        )
        assert build_manual_trajectory(req)["best_total_kg"] == 520

    def test_meet_count_matches_entries(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, m, 1), total_kg=500)
                for m in range(1, 5)
            ],
        )
        assert build_manual_trajectory(req)["meet_count"] == 4

    def test_latest_weight_class_from_last_meet(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[
                ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, weight_class="83"),
                ManualMeetEntry(date=date(2024, 3, 1), total_kg=520, weight_class="93"),
            ],
        )
        assert build_manual_trajectory(req)["latest_weight_class"] == "93"

    def test_federation_is_manual_marker(self):
        req = ManualTrajectoryRequest(
            name="X", sex="M",
            entries=[ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)],
        )
        result = build_manual_trajectory(req)
        assert result["federation"] == "(manual)"
        assert result["meets"][0]["Federation"] == "(manual)"
