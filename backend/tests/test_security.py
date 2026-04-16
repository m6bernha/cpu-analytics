"""Security and hardening tests.

Covers input validation, LIKE wildcard escaping, and Pydantic bounds.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from backend.app.lifters import search_lifters
from backend.app.manual import ManualMeetEntry, ManualTrajectoryRequest


class TestSearchWildcardEscaping:
    def test_percent_wildcard_escaped(self, test_conn):
        """A search for '%%' should not match everything."""
        # Our fixture has lifters with various names. "%%" should not match
        # them all — it should match only literal "%" in names, which none
        # have.
        results = search_lifters(q="%%", country="Canada", parent_federation="IPF")
        assert results == []

    def test_underscore_wildcard_escaped(self, test_conn):
        """Underscore should not match any single character."""
        # "_ob" should NOT match "Bob" anymore (underscore is literal now).
        results = search_lifters(q="_ob", country="Canada", parent_federation="IPF")
        assert all("_ob" in r["Name"].lower() for r in results)

    def test_long_query_truncated(self, test_conn):
        """A 1000-character query should not hang; it's truncated to 50."""
        results = search_lifters(q="a" * 1000, country="Canada", parent_federation="IPF")
        # Just confirm it returns without crashing; result list can be anything
        assert isinstance(results, list)


class TestManualValidation:
    def test_entries_length_capped(self):
        """> 200 entries raises ValidationError."""
        entries = [
            ManualMeetEntry(date=date(2024, 1, 1), total_kg=500)
            for _ in range(201)
        ]
        with pytest.raises(ValidationError):
            ManualTrajectoryRequest(sex="M", entries=entries)

    def test_total_kg_upper_bound(self):
        """total_kg > 2000 raises."""
        with pytest.raises(ValidationError):
            ManualMeetEntry(date=date(2024, 1, 1), total_kg=5000)

    def test_pre_1960_date_rejected(self):
        with pytest.raises(ValidationError):
            ManualMeetEntry(date=date(1950, 1, 1), total_kg=500)

    def test_far_future_date_rejected(self):
        """A date > next year raises."""
        with pytest.raises(ValidationError):
            ManualMeetEntry(date=date(2099, 1, 1), total_kg=500)

    def test_valid_entry_accepted(self):
        """A reasonable entry passes."""
        entry = ManualMeetEntry(date=date(2024, 6, 1), total_kg=500)
        assert entry.total_kg == 500

    def test_sex_must_be_m_or_f(self):
        with pytest.raises(ValidationError):
            ManualTrajectoryRequest(sex="Other", entries=[])

    def test_bodyweight_range(self):
        with pytest.raises(ValidationError):
            ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, bodyweight_kg=10)
        with pytest.raises(ValidationError):
            ManualMeetEntry(date=date(2024, 1, 1), total_kg=500, bodyweight_kg=500)
