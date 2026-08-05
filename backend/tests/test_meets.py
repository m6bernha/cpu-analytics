"""Tests for meet result pages.

Synthetic fixture (conftest._ROWS) recap for the two meets used here:

  "BC Open"        Bob B, Raw SBD, 4 meets 2022-2025 (one per year)
  "BC Bench Bash"  Bob B, Raw B (bench only), 2023-06-01
  "Ontario Champs" Alice A, Raw SBD, 2022 / 2023 / 2025
  "Ontario Equipped" Ella E, Multi-ply SBD, 2023-05-01 + 2024-05-01
"""

from __future__ import annotations

from backend.app import meets


class TestLookup:
    def test_unknown_meet_returns_shape_complete_empty(self, test_conn):
        r = meets.get_meet_results("No Such Meet", "2025-01-01")
        assert r["found"] is False
        assert r["groups"] == []
        assert r["n_results"] == 0
        assert r["n_lifters"] == 0
        assert r["canadian_scope_only"] is True

    def test_malformed_date_is_rejected_without_querying(self, test_conn):
        for bad in ["", "2025", "01-15-2025", "not-a-date"]:
            assert meets.get_meet_results("BC Open", bad)["found"] is False

    def test_empty_name_is_rejected(self, test_conn):
        assert meets.get_meet_results("", "2025-01-15")["found"] is False

    def test_date_must_match_the_meet(self, test_conn):
        """A real meet name with the wrong date is not a meet."""
        assert meets.get_meet_results("BC Open", "2019-01-15")["found"] is False


class TestResults:
    def test_finds_a_meet_and_reports_metadata(self, test_conn):
        r = meets.get_meet_results("BC Open", "2025-01-15")
        assert r["found"] is True
        assert r["meet_name"] == "BC Open"
        assert r["date"] == "2025-01-15"
        assert r["federation"] == "CPU"
        assert r["n_results"] == 1
        assert r["n_lifters"] == 1

    def test_group_carries_its_own_axes(self, test_conn):
        g = meets.get_meet_results("BC Open", "2025-01-15")["groups"][0]
        assert (g["sex"], g["equipment"], g["event"], g["weight_class"]) == (
            "M", "Raw", "SBD", "83",
        )
        assert g["n_results"] == 1

    def test_result_row_carries_the_full_lift_record(self, test_conn):
        row = meets.get_meet_results("BC Open", "2025-01-15")["groups"][0]["results"][0]
        assert row["name"] == "Bob B"
        assert row["total_kg"] == 565.0
        assert row["squat_kg"] == 205.0
        assert row["bench_kg"] == 135.0
        assert row["deadlift_kg"] == 225.0
        assert row["place"] == "1"

    def test_non_sbd_events_are_included(self, test_conn):
        """A meet page is a record: a bench-only lifter must not vanish."""
        r = meets.get_meet_results("BC Bench Bash", "2023-06-01")
        assert r["found"] is True
        assert r["groups"][0]["event"] == "B"
        assert r["groups"][0]["results"][0]["name"] == "Bob B"

    def test_equipped_lifters_are_included(self, test_conn):
        r = meets.get_meet_results("Ontario Equipped", "2024-05-01")
        assert r["found"] is True
        assert r["groups"][0]["equipment"] == "Multi-ply"
        assert r["groups"][0]["results"][0]["name"] == "Ella E"


class TestOrdering:
    def test_places_sort_numerically_not_lexically(self):
        got = sorted(["10", "2", "1", "21", "3"], key=meets._place_key)
        assert got == ["1", "2", "3", "10", "21"]

    def test_non_numeric_places_sort_last(self):
        got = sorted(["DQ", "2", "NS", "1"], key=meets._place_key)
        assert got[:2] == ["1", "2"]
        assert set(got[2:]) == {"DQ", "NS"}

    def test_weight_classes_sort_numerically_with_plus_after(self):
        got = sorted(["120", "83", "120+", "93", "59"], key=meets._weight_class_key)
        assert got == ["59", "83", "93", "120", "120+"]

    def test_unparseable_weight_class_sorts_last(self):
        got = sorted(["83", None, "93"], key=meets._weight_class_key)
        assert got[-1] is None

    def test_known_values_sort_in_declared_order(self):
        got = sorted(["Single-ply", "Raw"], key=lambda v: meets._rank_in(v, meets._EQUIPMENT_ORDER))
        assert got == ["Raw", "Single-ply"]
        got = sorted(["B", "SBD"], key=lambda v: meets._rank_in(v, meets._EVENT_ORDER))
        assert got == ["SBD", "B"]

    def test_unknown_values_sort_after_known_ones(self):
        got = sorted(["Zzz", "Raw"], key=lambda v: meets._rank_in(v, meets._EQUIPMENT_ORDER))
        assert got == ["Raw", "Zzz"]

    def test_open_division_sorts_before_others(self):
        got = sorted(["Masters 1", "Open", "Juniors"], key=meets._division_key)
        assert got == ["Open", "Juniors", "Masters 1"]

    def test_missing_division_sorts_last(self):
        got = sorted(["Open", None, "Juniors", ""], key=meets._division_key)
        assert got[0] == "Open"
        assert set(got[2:]) == {None, ""}

    def test_results_group_by_division_before_place(self, test_conn):
        """CPU places PER DIVISION, so a class can hold several 1st places.
        Ordering by place alone would render a wall of 1s."""
        rows = [
            {"division": "Masters 1", "place": "1"},
            {"division": "Open", "place": "2"},
            {"division": "Masters 1", "place": "2"},
            {"division": "Open", "place": "1"},
        ]
        rows.sort(
            key=lambda r: (meets._division_key(r["division"]), meets._place_key(r["place"]))
        )
        assert [(r["division"], r["place"]) for r in rows] == [
            ("Open", "1"), ("Open", "2"), ("Masters 1", "1"), ("Masters 1", "2"),
        ]
