"""Tests for QT coverage computation.

Uses the synthetic fixture from conftest.py.
"""

from __future__ import annotations

from backend.app.qt import (
    compute_blocks,
    compute_coverage,
    era_window_for_standard,
    get_qt_standards,
    lifter_best_totals,
    pct_meeting_qt,
    window_24mo_to_nationals,
)
import pandas as pd


class TestEraWindows:
    def test_pre2025_window(self):
        w = era_window_for_standard("pre2025")
        assert w.start is None
        assert w.end == pd.Timestamp("2025-01-01")

    def test_2025_window(self):
        w = era_window_for_standard("2025")
        assert w.start == pd.Timestamp("2025-01-01")
        assert w.end == pd.Timestamp("2027-01-01")

    def test_2027_window(self):
        w = era_window_for_standard("2027")
        assert w.start == pd.Timestamp("2027-01-01")
        assert w.end is None

    def test_nationals_24mo_2025(self):
        w = window_24mo_to_nationals("2025")
        assert w.start == pd.Timestamp("2023-03-01")
        assert w.end == pd.Timestamp("2025-03-01")


class TestBestTotalsAndPct:
    def test_lifter_best_totals(self):
        df = pd.DataFrame([
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "Bob", "TotalKg": 500},
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "Bob", "TotalKg": 550},
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "Alice", "TotalKg": 300},
        ])
        best = lifter_best_totals(df)
        assert len(best) == 2
        bob_best = best[best["Name"] == "Bob"]["BestTotalKg"].iloc[0]
        assert bob_best == 550

    def test_pct_meeting_qt(self):
        df = pd.DataFrame({"BestTotalKg": [400, 500, 600]})
        # Threshold 500 → 2 of 3 meet or exceed → 66.67%
        assert abs(pct_meeting_qt(df, 500) - (200 / 3)) < 0.01

    def test_pct_meeting_qt_empty(self):
        df = pd.DataFrame({"BestTotalKg": []})
        result = pct_meeting_qt(df, 500)
        # NaN for empty denominator
        assert result != result  # NaN != NaN


class TestQtStandards:
    def test_get_qt_standards(self, test_conn):
        df = get_qt_standards()
        assert not df.empty
        assert {"Sex", "Level", "WeightClass", "QT_pre2025", "QT_2025", "QT_2027"} <= set(df.columns)


class TestComputeCoverage:
    def test_returns_expected_columns(self, test_conn):
        df = compute_coverage(
            country="Canada", federation="CPU", equipment="Raw",
            tested="Yes", event="SBD", age_filter="open",
        )
        required_cols = {"Sex", "Level", "WeightClass"}
        assert required_cols <= set(df.columns)

    def test_invalid_age_filter_raises(self, test_conn):
        import pytest
        with pytest.raises(ValueError):
            compute_coverage(age_filter="junior")


class TestComputeBlocks:
    def test_always_returns_four_keys(self, test_conn):
        """Regression test: blocks must always include all four combos."""
        blocks = compute_blocks(
            country="Canada", federation="CPU", equipment="Raw",
            tested="Yes", event="SBD",
        )
        assert set(blocks.keys()) == {
            "M_Nationals", "M_Regionals", "F_Nationals", "F_Regionals",
        }

    def test_empty_filter_still_has_keys(self, test_conn):
        """With a filter that matches nothing, all four keys are still []."""
        blocks = compute_blocks(
            country="Canada", federation="CPU", equipment="Single-ply",
            tested="Yes", event="SBD",
        )
        for k in ["M_Nationals", "M_Regionals", "F_Nationals", "F_Regionals"]:
            assert isinstance(blocks[k], list)
