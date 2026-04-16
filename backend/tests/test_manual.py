"""Tests for manual trajectory computation."""

from __future__ import annotations

from datetime import date

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
