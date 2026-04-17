"""Hypothesis property-based tests for canonical_weight_class.

These explore the input space Hypothesis-style instead of hand-picking
edge cases, so regressions like the drop-53 bug would be caught even if
no one wrote a literal for the offending bodyweight.

Complements test_weight_class.py (which pins specific values).
"""

from __future__ import annotations

import pandas as pd
from hypothesis import given, settings, strategies as st

from backend.app.weight_class import (
    MEN_BOUNDS,
    WOMEN_BOUNDS,
    canonical_weight_class,
    canonical_weight_class_bulk,
)


MEN_CLASSES = {str(b) for b in MEN_BOUNDS} | {"120+"}
WOMEN_CLASSES = {str(b) for b in WOMEN_BOUNDS} | {"84+"}

MEN_RANK: dict[str, int] = {str(b): i for i, b in enumerate(MEN_BOUNDS)}
MEN_RANK["120+"] = len(MEN_BOUNDS)
WOMEN_RANK: dict[str, int] = {str(b): i for i, b in enumerate(WOMEN_BOUNDS)}
WOMEN_RANK["84+"] = len(WOMEN_BOUNDS)


def _is_nan(x) -> bool:
    try:
        return pd.isna(x)
    except (TypeError, ValueError):
        return False


class TestReturnSet:
    @given(bw=st.floats(min_value=53.5, max_value=200, allow_nan=False, allow_infinity=False))
    def test_men_valid_range_returns_men_class(self, bw: float):
        result = canonical_weight_class("M", bw)
        assert result in MEN_CLASSES, f"bw={bw} returned {result!r}"

    @given(bw=st.floats(min_value=46.5, max_value=150, allow_nan=False, allow_infinity=False))
    def test_women_valid_range_returns_women_class(self, bw: float):
        result = canonical_weight_class("F", bw)
        assert result in WOMEN_CLASSES, f"bw={bw} returned {result!r}"

    @given(bw=st.floats(min_value=-50, max_value=53.499, allow_nan=False, allow_infinity=False))
    def test_men_below_cutoff_nan(self, bw: float):
        assert _is_nan(canonical_weight_class("M", bw))

    @given(bw=st.floats(min_value=-50, max_value=46.499, allow_nan=False, allow_infinity=False))
    def test_women_below_cutoff_nan(self, bw: float):
        assert _is_nan(canonical_weight_class("F", bw))


class TestMonotonic:
    @given(
        bw1=st.floats(min_value=53.5, max_value=200, allow_nan=False, allow_infinity=False),
        bw2=st.floats(min_value=53.5, max_value=200, allow_nan=False, allow_infinity=False),
    )
    def test_men_bodyweight_monotonic(self, bw1: float, bw2: float):
        """Heavier bodyweight must map to a class with greater-or-equal rank."""
        if bw1 > bw2:
            bw1, bw2 = bw2, bw1
        c1 = canonical_weight_class("M", bw1)
        c2 = canonical_weight_class("M", bw2)
        assert MEN_RANK[c1] <= MEN_RANK[c2], (
            f"non-monotonic: {bw1} -> {c1}, {bw2} -> {c2}"
        )

    @given(
        bw1=st.floats(min_value=46.5, max_value=150, allow_nan=False, allow_infinity=False),
        bw2=st.floats(min_value=46.5, max_value=150, allow_nan=False, allow_infinity=False),
    )
    def test_women_bodyweight_monotonic(self, bw1: float, bw2: float):
        if bw1 > bw2:
            bw1, bw2 = bw2, bw1
        c1 = canonical_weight_class("F", bw1)
        c2 = canonical_weight_class("F", bw2)
        assert WOMEN_RANK[c1] <= WOMEN_RANK[c2], (
            f"non-monotonic: {bw1} -> {c1}, {bw2} -> {c2}"
        )


class TestRegressionGuards:
    @given(bw=st.floats(min_value=54.0, max_value=58.999, allow_nan=False, allow_infinity=False))
    def test_men_54_to_58_all_map_to_59(self, bw: float):
        """Regression guard for the drop-53 bug.

        Men in [53.5, 59) are promoted to the 59 bucket so they don't
        disappear. If someone re-raises the cutoff to 59, this test fails
        for any bw in [53.5, 59).
        """
        assert canonical_weight_class("M", bw) == "59"

    def test_men_53_5_exactly_maps_to_59(self):
        """The lower boundary of the valid men's range."""
        assert canonical_weight_class("M", 53.5) == "59"

    def test_women_84_5_maps_to_shw(self):
        """Women above 84.0 are superheavy."""
        assert canonical_weight_class("F", 84.5) == "84+"

    def test_women_47_5_stays_in_47(self):
        """The upper edge of the 47 class."""
        assert canonical_weight_class("F", 47.5) == "47"

    def test_women_47_6_promoted_to_52(self):
        """Just above 47.5, the floor snaps to 52."""
        assert canonical_weight_class("F", 47.6) == "52"


class TestInvalidSex:
    @given(
        sex=st.sampled_from(["Mx", "", "X", "1", "Other", "NB", "mf"]),
        bw=st.floats(min_value=40, max_value=200, allow_nan=False, allow_infinity=False),
    )
    def test_invalid_sex_returns_nan(self, sex: str, bw: float):
        assert _is_nan(canonical_weight_class(sex, bw))

    def test_lowercase_sex_normalized(self):
        """Sex is strip+upper'd, so 'm' and 'f ' are valid."""
        assert canonical_weight_class("m", 83) == "83"
        assert canonical_weight_class("f", 63) == "63"
        assert canonical_weight_class("M ", 83) == "83"


class TestPlusSuffix:
    @given(bw_base=st.floats(min_value=53.5, max_value=200, allow_nan=False, allow_infinity=False))
    def test_men_plus_suffix_always_shw(self, bw_base: float):
        """A '+' suffix on men's input always means superheavy."""
        wc_str = f"{bw_base:.1f}+"
        assert canonical_weight_class("M", wc_str) == "120+"

    @given(bw_base=st.floats(min_value=47.6, max_value=150, allow_nan=False, allow_infinity=False))
    def test_women_plus_suffix_above_47_is_shw(self, bw_base: float):
        """A '+' suffix on women's input, above the 47 band, means 84+."""
        wc_str = f"{bw_base:.1f}+"
        assert canonical_weight_class("F", wc_str) == "84+"


class TestBulkMatchesRowwiseHypothesis:
    @given(
        sex=st.sampled_from(["M", "F", "m", "f", "Mx", "", "X"]),
        bw=st.one_of(
            st.floats(min_value=-50, max_value=250, allow_nan=False, allow_infinity=False),
            st.sampled_from([None, "SHW", "84+", "120+", "59+", "abc", ""]),
        ),
    )
    @settings(max_examples=200)
    def test_bulk_equals_rowwise(self, sex, bw):
        """Bulk vectorized version must produce identical output to rowwise."""
        row_result = canonical_weight_class(sex, bw)
        bulk_result = canonical_weight_class_bulk(
            pd.Series([sex]), pd.Series([bw])
        ).iloc[0]
        if _is_nan(row_result):
            assert _is_nan(bulk_result), (
                f"row NaN, bulk {bulk_result!r} for ({sex!r}, {bw!r})"
            )
        else:
            assert row_result == bulk_result, (
                f"row {row_result!r}, bulk {bulk_result!r} for ({sex!r}, {bw!r})"
            )
