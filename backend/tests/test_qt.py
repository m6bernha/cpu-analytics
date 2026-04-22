"""Tests for QT coverage computation.

Uses the synthetic fixture from conftest.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.qt import (
    apply_time_window,
    compute_blocks,
    compute_coverage,
    era_window_for_standard,
    get_qt_standards,
    lifter_best_totals,
    pct_meeting_qt,
    window_24mo_to_nationals,
)


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

    def test_division_param_accepted(self, test_conn):
        """Non-Open division is accepted (falls back to Open numbers for v1)."""
        blocks = compute_blocks(
            country="Canada", federation="CPU", equipment="Raw",
            tested="Yes", event="SBD", division="Junior",
        )
        assert set(blocks.keys()) == {
            "M_Nationals", "M_Regionals", "F_Nationals", "F_Regionals",
        }


class TestAgeDivisionFallback:
    def test_open_reports_no_override(self):
        """Open has no override -- the base qt_standards parquet IS the Open table."""
        from backend.app.data_static.qt_by_division import has_age_specific_qt
        assert has_age_specific_qt("Open") is False

    def test_non_open_reports_no_override(self):
        """Every non-Open division falls back until powerlifting.ca is transcribed."""
        from backend.app.data_static.qt_by_division import has_age_specific_qt
        for d in ["Sub-Junior", "Junior", "Master 1", "Master 2", "Master 3", "Master 4"]:
            assert has_age_specific_qt(d) is False, f"{d} should fall back"

    def test_unknown_division_reports_no_override(self):
        from backend.app.data_static.qt_by_division import has_age_specific_qt
        assert has_age_specific_qt("Youth 1") is False


class TestLifterBestTotalsEdgeCases:
    def test_empty_dataframe_returns_empty(self):
        empty = pd.DataFrame(
            columns=["Sex", "CanonicalWeightClass", "Name", "TotalKg"]
        )
        result = lifter_best_totals(empty)
        assert len(result) == 0
        assert "BestTotalKg" in result.columns

    def test_single_lifter_single_row(self):
        df = pd.DataFrame([
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "Solo", "TotalKg": 500},
        ])
        result = lifter_best_totals(df)
        assert len(result) == 1
        assert result["BestTotalKg"].iloc[0] == 500

    def test_all_nan_totals(self):
        """All DQ / bombed meets: best is NaN per lifter."""
        df = pd.DataFrame([
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "A", "TotalKg": np.nan},
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "A", "TotalKg": np.nan},
            {"Sex": "F", "CanonicalWeightClass": "63", "Name": "B", "TotalKg": np.nan},
        ])
        result = lifter_best_totals(df)
        assert len(result) == 2
        assert result["BestTotalKg"].isna().all()

    def test_mixed_sex_and_class_groups_correctly(self):
        df = pd.DataFrame([
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "Bob", "TotalKg": 500},
            {"Sex": "M", "CanonicalWeightClass": "93", "Name": "Bob", "TotalKg": 550},
            {"Sex": "F", "CanonicalWeightClass": "83", "Name": "Bob", "TotalKg": 300},
        ])
        result = lifter_best_totals(df)
        assert len(result) == 3

    def test_max_across_multiple_meets(self):
        df = pd.DataFrame([
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "A", "TotalKg": 500},
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "A", "TotalKg": 480},
            {"Sex": "M", "CanonicalWeightClass": "83", "Name": "A", "TotalKg": 520},
        ])
        result = lifter_best_totals(df)
        assert result["BestTotalKg"].iloc[0] == 520


class TestPctMeetingQtEdgeCases:
    def test_all_above_threshold(self):
        df = pd.DataFrame({"BestTotalKg": [600, 700, 800]})
        assert pct_meeting_qt(df, 500) == 100.0

    def test_none_above_threshold(self):
        df = pd.DataFrame({"BestTotalKg": [100, 200, 300]})
        assert pct_meeting_qt(df, 500) == 0.0

    def test_threshold_equal_to_total_counts_as_met(self):
        df = pd.DataFrame({"BestTotalKg": [500, 500, 500]})
        assert pct_meeting_qt(df, 500) == 100.0

    def test_threshold_zero_everyone_meets(self):
        df = pd.DataFrame({"BestTotalKg": [100, 200, 300]})
        assert pct_meeting_qt(df, 0) == 100.0


class TestApplyTimeWindow:
    def test_open_start_window(self):
        df = pd.DataFrame({"Date": [
            pd.Timestamp("2020-01-01"), pd.Timestamp("2026-01-01"),
        ]})
        w = era_window_for_standard("pre2025")
        out = apply_time_window(df, w)
        assert len(out) == 1
        assert out["Date"].iloc[0] == pd.Timestamp("2020-01-01")

    def test_open_end_window(self):
        df = pd.DataFrame({"Date": [
            pd.Timestamp("2020-01-01"), pd.Timestamp("2027-06-01"),
        ]})
        w = era_window_for_standard("2027")
        out = apply_time_window(df, w)
        assert len(out) == 1
        assert out["Date"].iloc[0] == pd.Timestamp("2027-06-01")

    def test_bounded_window(self):
        df = pd.DataFrame({"Date": [
            pd.Timestamp("2024-01-01"),
            pd.Timestamp("2025-06-01"),
            pd.Timestamp("2027-02-01"),
        ]})
        w = era_window_for_standard("2025")
        out = apply_time_window(df, w)
        assert len(out) == 1
        assert out["Date"].iloc[0] == pd.Timestamp("2025-06-01")


class TestComputeCoverageEdgeCases:
    def test_empty_cohort_all_pct_nan(self, test_conn):
        """Equipment that matches nothing: every Pct_* cell is NaN."""
        df = compute_coverage(
            country="Canada", federation="CPU", equipment="Single-ply",
            tested="Yes", event="SBD", age_filter="open",
        )
        # Still one row per QT standard row
        assert len(df) > 0
        pct_cols = [c for c in df.columns if c.startswith("Pct_")]
        assert len(pct_cols) > 0
        for c in pct_cols:
            assert df[c].isna().all(), f"expected all NaN in {c}"

    def test_non_matching_country_empty(self, test_conn):
        df = compute_coverage(
            country="Narnia", federation="CPU", equipment="Raw",
            tested="Yes", event="SBD", age_filter="open",
        )
        pct_cols = [c for c in df.columns if c.startswith("Pct_")]
        for c in pct_cols:
            assert df[c].isna().all()

    def test_age_open_excludes_junior_meets(self, test_conn):
        """With age_filter='open', Alice's Junior-division pre2025 meets
        are excluded. F/63 Nationals has no pre2025 Open data -> NaN."""
        df = compute_coverage(age_filter="open")
        row = df[(df["Sex"] == "F") & (df["WeightClass"] == "63") & (df["Level"] == "Nationals")]
        assert len(row) == 1
        assert pd.isna(row["Pct_AllEra_pre2025"].iloc[0])

    def test_age_all_includes_junior_meets(self, test_conn):
        """With age_filter='all', Alice's Junior pre2025 meets count."""
        df = compute_coverage(age_filter="all")
        row = df[(df["Sex"] == "F") & (df["WeightClass"] == "63") & (df["Level"] == "Nationals")]
        assert len(row) == 1
        # Alice had pre2025 meets at 280/305; both below 347.5 -> 0%
        assert row["Pct_AllEra_pre2025"].iloc[0] == 0.0

    def test_2027_era_no_data_returns_nan(self, test_conn):
        """No fixture rows are in the 2027 era -> Pct_AllEra_2027 is NaN."""
        df = compute_coverage(age_filter="open")
        assert df["Pct_AllEra_2027"].isna().all()

    def test_invalid_age_filter_raises(self, test_conn):
        with pytest.raises(ValueError):
            compute_coverage(age_filter="junior")

    def test_mixed_sex_rows_present(self, test_conn):
        """Both M and F rows appear when both sexes have QT standards."""
        df = compute_coverage(age_filter="open")
        assert (df["Sex"] == "M").any()
        assert (df["Sex"] == "F").any()


class TestComputeBlocksEdgeCases:
    def test_weight_classes_sorted_within_block(self, test_conn):
        """Within each block the WeightClass list is in ascending order."""
        blocks = compute_blocks(
            country="Canada", federation="CPU", equipment="Raw",
            tested="Yes", event="SBD",
        )

        def wc_key(s: str) -> float:
            if s.endswith("+"):
                return float(s.rstrip("+")) + 0.5
            return float(s)

        for k, rows in blocks.items():
            if len(rows) <= 1:
                continue
            wcs = [r["WeightClass"] for r in rows]
            keys = [wc_key(w) for w in wcs]
            assert keys == sorted(keys), f"{k} not sorted: {wcs}"

    def test_record_shape(self, test_conn):
        """Each row has the expected 4 keys."""
        blocks = compute_blocks(
            country="Canada", federation="CPU", equipment="Raw",
            tested="Yes", event="SBD",
        )
        expected_keys = {"WeightClass", "pct_pre2025", "pct_2025", "pct_2027_today"}
        for rows in blocks.values():
            for row in rows:
                assert set(row.keys()) == expected_keys


# -------------------------------------------------------------------------
# Live-scrape QT tests (2026+)
# -------------------------------------------------------------------------

from backend.app.qt import (  # noqa: E402
    compute_live_coverage,
    get_live_qt_filters,
    load_live_qt,
)


class TestLoadLiveQt:
    def test_no_filter_returns_all_rows(self, test_conn):
        df = load_live_qt(test_conn)
        # Conftest fixture has 7 qt_current rows.
        assert len(df) == 7

    def test_filter_by_sex_and_year(self, test_conn):
        df = load_live_qt(test_conn, sex="M", effective_year=2026)
        assert len(df) >= 1
        assert (df["sex"] == "M").all()
        assert (df["effective_year"] == 2026).all()

    def test_filter_by_region(self, test_conn):
        df = load_live_qt(
            test_conn, effective_year=2027, region="Western/Central",
        )
        assert not df.empty
        assert (df["region"] == "Western/Central").all()

    def test_filter_by_division_junior(self, test_conn):
        df = load_live_qt(test_conn, division="Junior")
        assert len(df) == 1
        assert df.iloc[0]["division"] == "Junior"


class TestGetLiveQtFilters:
    def test_returns_expected_shape(self, test_conn):
        f = get_live_qt_filters()
        assert f["live_data_available"] is True
        assert "M" in f["sexes"] and "F" in f["sexes"]
        assert "Nationals" in f["levels"]
        assert "Regionals" in f["levels"]
        assert "Western/Central" in f["regions"]
        assert "Eastern" in f["regions"]
        assert f["divisions"] == ["Junior", "Open"]  # CPU canonical order
        assert 2026 in f["effective_years"]
        assert 2027 in f["effective_years"]
        assert f["fetched_at"] is not None

    def test_degraded_mode_when_live_unavailable(self, test_conn, monkeypatch):
        import backend.app.data as data_mod
        monkeypatch.setattr(data_mod, "_qt_current_available", False)
        f = get_live_qt_filters()
        assert f == {"live_data_available": False}


class TestComputeLiveCoverage:
    def test_men_open_nationals_2026_83(self, test_conn):
        df = compute_live_coverage(
            sex="M", level="Nationals", effective_year=2026,
            division="Open",
        )
        row = df[df["weight_class"] == "83"].iloc[0]
        assert row["qt"] == 500.0
        assert row["n_lifters"] >= 1
        assert row["n_meeting_qt"] >= 1
        assert row["pct_meeting_qt"] is not None

    def test_region_filter_selects_correct_qt(self, test_conn):
        wc = compute_live_coverage(
            sex="M", level="Regionals", effective_year=2027,
            division="Open", region="Western/Central",
        )
        ea = compute_live_coverage(
            sex="M", level="Regionals", effective_year=2027,
            division="Open", region="Eastern",
        )
        wc_qt = wc[wc["weight_class"] == "83"].iloc[0]["qt"]
        ea_qt = ea[ea["weight_class"] == "83"].iloc[0]["qt"]
        assert wc_qt == 475.0
        assert ea_qt == 460.0

    def test_empty_result_when_no_matching_qt(self, test_conn):
        df = compute_live_coverage(
            sex="M", level="Nationals", effective_year=2026,
            division="Master 1",
        )
        assert df.empty

    def test_output_columns(self, test_conn):
        df = compute_live_coverage(
            sex="M", level="Nationals", effective_year=2026, division="Open",
        )
        assert list(df.columns) == [
            "weight_class", "qt", "n_lifters", "n_meeting_qt", "pct_meeting_qt",
        ]
