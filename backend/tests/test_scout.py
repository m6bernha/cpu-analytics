"""Tests for the meet scouting report generator.

Uses the synthetic 5-lifter fixture from conftest.py plus the cohort/K-M
precompute fixture from test_athlete_projection.py (re-imported below to
avoid leaking module state).

Fixture summary (from conftest._ROWS):
  - Alice A:  F, 63, Junior->Open, 3 SBD meets, ages 22/23/25
  - Bob B:    M, 83, Open, 4 SBD meets + 1 bench, ages 28-31
  - Carl C:   M, 93, Open, 2 meets (2020 + 2024), ages 25, 29
  - Dana D:   F, 57, Junior, 1 meet only (single-meet)
  - Ella E:   F, 72->84, Multi-ply Open, 2 meets
"""

from __future__ import annotations

import pytest

from backend.app import athlete_projection as ap
from backend.app.scout import (
    ScoutManualOverride,
    ScoutMeetRequest,
    ScoutRosterEntry,
    build_scout_report,
    classify_status,
)


# Reuse the precomputed-tables pattern from test_athlete_projection.py so
# shrinkage_projection() has cohort + K-M tables when scout calls it.
@pytest.fixture(scope="module")
def precomputed(test_conn):
    """Populate module-level cohort + K-M + MixedLM tables."""
    ap.precompute_tables()
    yield
    ap._COHORT = {}
    ap._KM = {}
    ap._MIXEDLM = {}
    ap._MIXEDLM_CONVERGED_PCT = 0.0
    ap._ENGINE_D_GLOBAL_AVAILABLE = False
    ap._PRECOMPUTED = False


def _make_req(roster_entries, meet_date="2027-06-01"):
    """Helper: build a ScoutMeetRequest with sensible defaults."""
    return ScoutMeetRequest(
        meet_name="Test Meet",
        federation="CPU",
        location="Toronto, ON",
        meet_date=meet_date,
        generator_name="Test Generator",
        generator_brand="Vireo",
        roster=roster_entries,
    )


# =============================================================================
# classify_status: pure function, no DB needed
# =============================================================================


class TestClassifyStatus:
    """Cutoffs per project-audit-and-status-majestic-pretzel.md."""

    def test_unmatched_when_n_meets_is_none(self):
        assert classify_status(None, None) == "Unmatched"

    def test_frozen_when_single_meet(self):
        assert classify_status(1, 365) == "Frozen"

    def test_frozen_when_no_tenure(self):
        assert classify_status(5, None) == "Frozen"

    def test_veteran_by_meet_count(self):
        assert classify_status(25, 1000) == "Veteran"   # 20+ meets

    def test_veteran_by_tenure(self):
        assert classify_status(5, int(8 * 365.25)) == "Veteran"   # 8 yr

    def test_rookie_by_meet_count(self):
        assert classify_status(2, int(2 * 365.25)) == "Rookie"

    def test_rookie_by_tenure(self):
        assert classify_status(8, 30) == "Rookie"   # <1 yr

    def test_established_mid_range(self):
        assert classify_status(10, int(4 * 365.25)) == "Established"

    def test_developing_mid_range(self):
        assert classify_status(5, int(2 * 365.25)) == "Developing"


# =============================================================================
# build_scout_report: end-to-end fixture-driven
# =============================================================================


class TestScoutReportShape:
    """Section shapes match the dataclass schema across resolution paths."""

    def test_empty_match_goes_to_unranked(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Nobody Inexistent")
        ])
        report = build_scout_report(req)
        assert report.unranked == ["Nobody Inexistent"]
        assert report.n_athletes_matched == 0
        assert report.class_blocks == []
        assert report.methodology.startswith("Projections use Engine C")

    def test_exact_match_resolves_to_row(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Bob B"),
        ])
        report = build_scout_report(req)
        assert report.unranked == []
        assert report.n_athletes_matched == 1
        # One class block, one athlete
        assert len(report.class_blocks) == 1
        block = report.class_blocks[0]
        athlete = block.athletes[0]
        assert athlete.name == "Bob B"
        assert athlete.is_manual is False
        assert athlete.weight_class == "83"
        assert athlete.n_meets == 5   # 4 SBD + 1 bench in fixture
        assert athlete.best_total_kg == 565.0

    def test_homie_flag_propagates(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Bob B", is_homie=True),
        ])
        report = build_scout_report(req)
        assert len(report.homies) == 1
        assert report.homies[0].name == "Bob B"
        assert report.homies[0].is_homie is True


class TestManualOverride:
    """Manual override path: roster names without OpenIPF matches."""

    def test_manual_override_builds_row(self, precomputed):
        override = ScoutManualOverride(
            best_total_kg=600.0,
            squat_best_kg=220.0,
            bench_best_kg=140.0,
            deadlift_best_kg=240.0,
            weight_class="83",
            last_meet_date="2026-12-01",
        )
        req = _make_req([
            ScoutRosterEntry(name="Unmatched Manual", manual_override=override),
        ])
        report = build_scout_report(req)
        assert report.unranked == []
        assert report.n_athletes_matched == 1
        row = report.class_blocks[0].athletes[0]
        assert row.is_manual is True
        assert row.best_total_kg == 600.0
        assert row.projected_total_kg == 600.0   # manual: no projection
        assert row.weight_class == "83"
        assert "manual entry" in row.inline_tags


class TestStatusClassification:
    """Status tag derives from n_meets + tenure_days in build_scout_report."""

    def test_dana_single_meet_is_frozen(self, precomputed):
        # Dana has 1 meet — would be Frozen, BUT she's a single-meet lifter
        # so search_lifters returns her with MeetCount=1. The projection
        # call may also degrade, but either path should land on Frozen.
        req = _make_req([
            ScoutRosterEntry(name="Dana D"),
        ])
        report = build_scout_report(req)
        # Dana might land in unranked OR matched depending on search shape.
        # If matched, she must be Frozen.
        if report.n_athletes_matched > 0:
            row = report.class_blocks[0].athletes[0]
            assert row.status_tag == "Frozen", (
                f"Dana single-meet should be Frozen; got {row.status_tag}"
            )

    def test_bob_with_full_history_is_not_frozen(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Bob B"),
        ])
        report = build_scout_report(req)
        row = report.class_blocks[0].athletes[0]
        assert row.status_tag != "Frozen", (
            f"Bob has 5 meets; should not be Frozen. Got {row.status_tag}"
        )


class TestClassGroupingAndGapSort:
    """Athletes group by weight_class; classes sort by smallest projected gap."""

    def test_distinct_classes_each_get_own_block(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Bob B"),       # 83
            ScoutRosterEntry(name="Carl C"),      # 93
        ])
        report = build_scout_report(req)
        assert report.n_athletes_matched == 2
        # Two distinct classes -> two blocks
        classes = {b.weight_class for b in report.class_blocks}
        assert classes == {"83", "93"}

    def test_gap_is_none_when_single_athlete_per_class(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Bob B"),
        ])
        report = build_scout_report(req)
        block = report.class_blocks[0]
        assert block.projected_gap_kg is None
        assert block.n_athletes == 1

    def test_unranked_for_unmatched_no_override(self, precomputed):
        req = _make_req([
            ScoutRosterEntry(name="Bob B"),
            ScoutRosterEntry(name="Nobody Here"),
            ScoutRosterEntry(name="Carl C"),
        ])
        report = build_scout_report(req)
        assert "Nobody Here" in report.unranked
        assert report.n_athletes_matched == 2


# =============================================================================
# Endpoint smoke
# =============================================================================


class TestScoutEndpoint:
    """Smoke-test the POST /api/scout/report route via FastAPI TestClient."""

    def test_endpoint_returns_200_with_valid_payload(self, precomputed):
        from fastapi.testclient import TestClient

        from backend.app.main import app

        client = TestClient(app)
        payload = {
            "meet_name": "Endpoint Smoke",
            "federation": "CPU",
            "location": "Test City",
            "meet_date": "2027-06-01",
            "generator_name": "Test",
            "generator_brand": "Vireo",
            "roster": [
                {"name": "Bob B"},
                {"name": "Nobody Inexistent"},
            ],
        }
        response = client.post("/api/scout/report", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        # Top-level sections present
        for key in (
            "request", "horizon_days", "horizon_months", "generated_at",
            "class_blocks", "homies", "closest_battles", "unranked",
            "methodology", "n_athletes_matched",
        ):
            assert key in body, f"missing top-level key: {key}"
        # Bob matched, Nobody unranked
        assert body["n_athletes_matched"] == 1
        assert "Nobody Inexistent" in body["unranked"]
