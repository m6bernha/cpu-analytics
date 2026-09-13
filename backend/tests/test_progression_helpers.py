"""Unit tests for the three cohort-filter helpers extracted from
``compute_progression`` / ``compute_lift_progression`` on 2026-09-11.

The extraction was gated by a 192-case golden comparison of both public
functions on the real parquet (identical within 1e-9). These tests lock the
helpers' own contracts on tiny hand-built frames so the two callers cannot
drift apart again.
"""
from __future__ import annotations

import pandas as pd
import pytest

from backend.app.progression import (
    _apply_age_filter_and_rebaseline,
    _apply_gap_filter,
    _apply_same_class_filter,
)


def _frame(rows: list[tuple]) -> pd.DataFrame:
    """rows: (Name, DaysFromFirst, Age, Value, ClassCount)."""
    return pd.DataFrame(rows, columns=["Name", "DaysFromFirst", "Age", "Value", "ClassCount"])


class TestGapFilter:
    def test_off_is_identity(self):
        df = _frame([("A", 0, 25, 500, 1), ("A", 800, 27, 520, 1)])
        assert _apply_gap_filter(df, None) is df

    def test_drops_the_lifter_with_a_long_gap_and_keeps_the_other(self):
        df = _frame([
            ("A", 0, 25, 500, 1), ("A", 800, 27, 520, 1),   # 800-day gap
            ("B", 0, 25, 500, 1), ("B", 100, 25, 510, 1), ("B", 200, 26, 515, 1),
        ])
        out = _apply_gap_filter(df, 12)   # 12 months ~ 365 days
        assert set(out["Name"]) == {"B"}
        assert not {"_prev_days", "_gap"} & set(out.columns)

    def test_gap_is_between_consecutive_meets_not_career_span(self):
        # Career span 400 days but every gap is 100: passes a 6-month filter.
        df = _frame([("A", d, 25, 500 + d / 10, 1) for d in (0, 100, 200, 300, 400)])
        assert len(_apply_gap_filter(df, 6)) == 5


class TestSameClassFilter:
    def test_off_or_missing_column_is_identity(self):
        df = _frame([("A", 0, 25, 500, 2)])
        assert _apply_same_class_filter(df, False) is df
        no_col = df.drop(columns=["ClassCount"])
        assert _apply_same_class_filter(no_col, True) is no_col

    def test_keeps_only_single_class_careers(self):
        df = _frame([("A", 0, 25, 500, 1), ("B", 0, 25, 500, 2)])
        assert set(_apply_same_class_filter(df, True)["Name"]) == {"A"}


class TestAgeFilterAndRebaseline:
    def test_all_or_none_is_identity(self):
        df = _frame([("A", 0, 25, 500, 1)])
        assert _apply_age_filter_and_rebaseline(df, None, {"Value": "Diff"}) is df
        assert _apply_age_filter_and_rebaseline(df, "All", {"Value": "Diff"}) is df

    def test_rebaselines_to_the_first_surviving_meet(self):
        # A Junior-era first meet at 400 kg must NOT anchor the Open deltas.
        df = _frame([
            ("A", 0, 20, 400, 1),     # Junior
            ("A", 400, 24, 480, 1),   # Open, first surviving
            ("A", 800, 25, 500, 1),   # Open
        ])
        out = _apply_age_filter_and_rebaseline(df, "Open", {"Value": "DiffFromFirst"})
        assert out["DaysFromFirst"].tolist() == [0, 400]
        assert out["DiffFromFirst"].tolist() == [0, 20]
        assert "AgeCategory" in out.columns
        assert not any(c.startswith("_First") for c in out.columns)

    def test_drops_lifters_left_with_one_meet_in_the_category(self):
        df = _frame([
            ("A", 0, 20, 400, 1), ("A", 400, 24, 480, 1),   # one Open meet only
            ("B", 0, 24, 450, 1), ("B", 300, 25, 470, 1),   # two Open meets
        ])
        out = _apply_age_filter_and_rebaseline(df, "Open", {"Value": "DiffFromFirst"})
        assert set(out["Name"]) == {"B"}

    def test_multi_column_mapping_rebaselines_each_lift(self):
        df = pd.DataFrame({
            "Name": ["A", "A", "A"],
            "DaysFromFirst": [0, 200, 400],
            "Age": [20, 24, 25],
            "Best3SquatKg": [150, 180, 190],
            "Best3BenchKg": [90, 100, 105],
        })
        out = _apply_age_filter_and_rebaseline(
            df, "Open", {"Best3SquatKg": "SquatDiff", "Best3BenchKg": "BenchDiff"},
        )
        assert out["SquatDiff"].tolist() == [0, 10]
        assert out["BenchDiff"].tolist() == [0, 5]
        assert out["DaysFromFirst"].tolist() == [0, 200]

    def test_renumbers_meet_number_only_when_present(self):
        df = _frame([("A", 0, 20, 400, 1), ("A", 400, 24, 480, 1), ("A", 800, 25, 500, 1)])
        df["MeetNumber"] = [1, 2, 3]
        out = _apply_age_filter_and_rebaseline(df, "Open", {"Value": "DiffFromFirst"})
        assert out["MeetNumber"].tolist() == [1, 2]
        without = _apply_age_filter_and_rebaseline(
            df.drop(columns=["MeetNumber"]), "Open", {"Value": "DiffFromFirst"},
        )
        assert "MeetNumber" not in without.columns

    def test_empty_after_filter_returns_empty_not_error(self):
        df = _frame([("A", 0, 20, 400, 1), ("A", 100, 21, 410, 1)])
        out = _apply_age_filter_and_rebaseline(df, "Master", {"Value": "DiffFromFirst"})
        assert out.empty


@pytest.mark.parametrize("gap", [None, 6, 12])
def test_gap_filter_never_reorders_columns_it_did_not_add(gap):
    df = _frame([("A", 0, 25, 500, 1), ("A", 30, 25, 505, 1)])
    out = _apply_gap_filter(df, gap)
    assert list(out.columns) == list(df.columns)
