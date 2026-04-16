"""Tests for lifter search and history endpoints.

Uses the synthetic fixture from conftest.py.
"""

from __future__ import annotations

import pytest
from backend.app.lifters import search_lifters, get_lifter_history


class TestSearchLifters:

    def test_search_by_name(self, test_conn):
        results = search_lifters(q="Bob", country="Canada", parent_federation="IPF")
        assert len(results) == 1
        assert results[0]["Name"] == "Bob B"

    def test_search_case_insensitive(self, test_conn):
        results = search_lifters(q="alice", country="Canada", parent_federation="IPF")
        assert len(results) == 1
        assert results[0]["Name"] == "Alice A"

    def test_search_min_length(self, test_conn):
        """Queries shorter than 2 chars return empty."""
        results = search_lifters(q="B", country="Canada", parent_federation="IPF")
        assert results == []

    def test_search_no_match(self, test_conn):
        results = search_lifters(q="Zzzzz", country="Canada", parent_federation="IPF")
        assert results == []

    def test_search_returns_best_total(self, test_conn):
        results = search_lifters(q="Bob", country="Canada", parent_federation="IPF")
        # Bob's best SBD total is 565, but search returns best across ALL events.
        # His bench-only total of 135 is lower, so BestTotalKg should be 565.
        assert results[0]["BestTotalKg"] == 565.0

    def test_search_returns_meet_count(self, test_conn):
        results = search_lifters(q="Bob", country="Canada", parent_federation="IPF")
        # Bob has 4 SBD + 1 bench = 5 total meets
        assert results[0]["MeetCount"] == 5


class TestGetLifterHistory:

    def test_found(self, test_conn):
        result = get_lifter_history("Bob B")
        assert result["found"] is True
        assert result["name"] == "Bob B"

    def test_not_found(self, test_conn):
        result = get_lifter_history("Nobody Exists")
        assert result["found"] is False
        assert result["meets"] == []

    def test_meet_count(self, test_conn):
        result = get_lifter_history("Bob B")
        # All 5 meets (4 SBD + 1 bench) should appear in history
        assert result["meet_count"] == 5
        assert len(result["meets"]) == 5

    def test_meets_ordered_by_date(self, test_conn):
        result = get_lifter_history("Bob B")
        dates = [m["Date"] for m in result["meets"]]
        assert dates == sorted(dates)

    def test_total_diff_from_first(self, test_conn):
        result = get_lifter_history("Bob B")
        # First meet total is 500. Diffs should be relative to that.
        first_total = result["meets"][0]["TotalKg"]
        assert first_total == 500.0
        for m in result["meets"]:
            expected_diff = m["TotalKg"] - first_total
            assert abs(m["TotalDiffFromFirst"] - expected_diff) < 0.01

    def test_includes_event_field(self, test_conn):
        result = get_lifter_history("Bob B")
        events = [m["Event"] for m in result["meets"]]
        assert "SBD" in events
        assert "B" in events  # bench-only meet

    def test_alice_has_division_transition(self, test_conn):
        result = get_lifter_history("Alice A")
        divisions = [m["Division"] for m in result["meets"]]
        assert "Juniors" in divisions
        assert "Open" in divisions
