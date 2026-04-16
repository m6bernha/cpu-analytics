"""Property tests for weight_class canonicalization.

Especially important: canonical_weight_class_bulk (vectorized) must
produce identical output to canonical_weight_class (row-wise) on every
input, since preprocess.py now uses the bulk version.
"""

from __future__ import annotations

import pandas as pd

from backend.app.weight_class import (
    canonical_weight_class,
    canonical_weight_class_bulk,
)


def _equivalent(sex: str, wc: str | float | None) -> bool:
    """Check row-wise == bulk for a single (sex, wc) pair."""
    row = canonical_weight_class(sex, wc)
    bulk = canonical_weight_class_bulk(pd.Series([sex]), pd.Series([wc])).iloc[0]
    # Both nan → equivalent
    if pd.isna(row) and pd.isna(bulk):
        return True
    return row == bulk


class TestMenCanonical:
    def test_sub_53_dropped(self):
        assert pd.isna(canonical_weight_class("M", "52.5"))
        assert _equivalent("M", "52.5")

    def test_57_rounds_up_to_59(self):
        assert canonical_weight_class("M", "57") == "59"
        assert _equivalent("M", "57")

    def test_exact_83(self):
        assert canonical_weight_class("M", "83") == "83"
        assert _equivalent("M", "83")

    def test_120_plus(self):
        assert canonical_weight_class("M", "125") == "120+"
        assert canonical_weight_class("M", "120+") == "120+"
        assert _equivalent("M", "125")
        assert _equivalent("M", "120+")

    def test_boundaries(self):
        # 66 exactly → 66
        assert canonical_weight_class("M", "66") == "66"
        # 66.001 → 74 (next bound up)
        assert canonical_weight_class("M", "66.5") == "74"
        assert _equivalent("M", "66")
        assert _equivalent("M", "66.5")


class TestWomenCanonical:
    def test_47_class(self):
        assert canonical_weight_class("F", "47") == "47"
        assert _equivalent("F", "47")

    def test_sub_46_5_dropped(self):
        assert pd.isna(canonical_weight_class("F", "45"))
        assert _equivalent("F", "45")

    def test_50_rounds_to_52(self):
        assert canonical_weight_class("F", "50") == "52"
        assert _equivalent("F", "50")

    def test_84_plus(self):
        assert canonical_weight_class("F", "90") == "84+"
        assert canonical_weight_class("F", "84+") == "84+"
        assert _equivalent("F", "90")
        assert _equivalent("F", "84+")


class TestBulkMatchesRowwise:
    def test_all_common_values(self):
        """Property: for a representative input set, bulk == rowwise."""
        inputs = [
            ("M", "53"), ("M", "59"), ("M", "66"), ("M", "74"), ("M", "83"),
            ("M", "93"), ("M", "105"), ("M", "120"), ("M", "120+"),
            ("M", "82.5"), ("M", "90"), ("M", "100"), ("M", "110"),
            ("M", "50"), ("M", None), ("M", "SHW"),
            ("F", "47"), ("F", "52"), ("F", "57"), ("F", "63"), ("F", "69"),
            ("F", "76"), ("F", "84"), ("F", "84+"),
            ("F", "45"), ("F", "52.5"), ("F", None),
            ("Mx", "83"),  # invalid sex
            ("M", ""),
        ]
        sex_series = pd.Series([x[0] for x in inputs])
        wc_series = pd.Series([x[1] for x in inputs])
        bulk_result = canonical_weight_class_bulk(sex_series, wc_series)

        for i, (sex, wc) in enumerate(inputs):
            row_result = canonical_weight_class(sex, wc)
            b = bulk_result.iloc[i]
            if pd.isna(row_result):
                assert pd.isna(b), f"row NaN but bulk {b!r} for ({sex!r}, {wc!r})"
            else:
                assert row_result == b, (
                    f"mismatch for ({sex!r}, {wc!r}): row={row_result!r} bulk={b!r}"
                )
