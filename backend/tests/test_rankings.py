"""Tests for the rankings leaderboard + GLP percentile curves.

Synthetic fixture recap (conftest._ROWS), filtered to the Raw SBD scope
this module ranks on:

  - Alice A: F, 63, Raw SBD, meets 2022-06-01 / 2023-06-01 / 2025-06-01,
    Goodlift 320 / 345 / 370
  - Bob B:   M, 83, Raw SBD, 2022..2025-01-15, Goodlift 350..390
             (plus a bench-only meet, excluded by Event='SBD')
  - Carl C:  M, 93, Raw SBD, 2020-03-01 + 2024-03-01, Goodlift 300 / 370
  - Dana D:  F, 57, Raw SBD, single meet 2024-09-01, Goodlift 290
  - Ella E:  F, Multi-ply, excluded by Equipment='Raw'

Newest in-scope meet is Alice's 2025-06-01, so the active window is
2023-06-02 .. 2025-06-01 and all four Raw lifters qualify.
"""

from __future__ import annotations

from backend.app import rankings


class TestWindowBounds:
    def test_window_anchors_to_newest_meet_not_today(self, test_conn):
        res = rankings.get_percentile_curves()
        assert res["window_end"] == "2025-06-01"
        assert res["window_start"] == "2023-06-02"


class TestPercentileCurves:
    def test_curves_are_per_sex_and_ascending(self, test_conn):
        curves = rankings.get_percentile_curves()["curves"]
        assert set(curves) == {"M", "F"}
        for sex in ("M", "F"):
            glp = curves[sex]["glp"]
            assert len(glp) == 101
            assert glp == sorted(glp)

    def test_counts_reflect_active_raw_sbd_lifters_only(self, test_conn):
        curves = rankings.get_percentile_curves()["curves"]
        # Ella is Multi-ply, Bob's bench-only meet is not SBD.
        assert curves["M"]["n"] == 2   # Bob, Carl
        assert curves["F"]["n"] == 2   # Alice, Dana

    def test_curve_endpoints_are_cohort_min_and_max(self, test_conn):
        curves = rankings.get_percentile_curves()["curves"]
        # Men: Carl best 370, Bob best 390.
        assert curves["M"]["glp"][0] == 370.0
        assert curves["M"]["glp"][100] == 390.0
        # Women: Dana 290, Alice best 370.
        assert curves["F"]["glp"][0] == 290.0
        assert curves["F"]["glp"][100] == 370.0


class TestLeaderboard:
    def test_ranks_by_glp_descending_with_name_tiebreak(self, test_conn):
        res = rankings.compute_leaderboard()
        names = [(r["rank"], r["name"]) for r in res["rows"]]
        assert names == [
            (1, "Bob B"),      # 390
            (2, "Alice A"),    # 370, alphabetical tiebreak
            (3, "Carl C"),     # 370
            (4, "Dana D"),     # 290
        ]
        assert res["n_total"] == 4
        assert res["metric"] == "glp"

    def test_row_columns_come_from_the_same_meet(self, test_conn):
        """Best-meet row, not independent maxima across a career."""
        row = next(r for r in rankings.compute_leaderboard()["rows"] if r["name"] == "Bob B")
        # Bob's best GLP meet is 2025-01-15: total 565, class 83.
        assert row["glp"] == 390.0
        assert row["total_kg"] == 565.0
        assert row["date"] == "2025-01-15"
        assert row["weight_class"] == "83"
        # Windowed count, not career: Bob has 4 Raw SBD meets but only
        # 2024-01-15 and 2025-01-15 fall inside the active window.
        assert row["n_meets_in_window"] == 2

    def test_metric_total_reorders(self, test_conn):
        res = rankings.compute_leaderboard(metric="total")
        assert res["metric"] == "total"
        # By total: Carl 600, Bob 565, Alice 330, Dana 225.
        assert [r["name"] for r in res["rows"]] == [
            "Carl C", "Bob B", "Alice A", "Dana D",
        ]

    def test_unknown_metric_falls_back_to_glp(self, test_conn):
        res = rankings.compute_leaderboard(metric="; DROP TABLE openipf")
        assert res["metric"] == "glp"
        assert res["rows"][0]["name"] == "Bob B"

    def test_sex_filter(self, test_conn):
        res = rankings.compute_leaderboard(sex="F")
        assert [r["name"] for r in res["rows"]] == ["Alice A", "Dana D"]
        assert res["n_total"] == 2
        # Rank restarts within the filtered set.
        assert res["rows"][0]["rank"] == 1

    def test_weight_class_filter(self, test_conn):
        res = rankings.compute_leaderboard(weight_class="83")
        assert [r["name"] for r in res["rows"]] == ["Bob B"]

    def test_division_filter_uses_canonical_aliases(self, test_conn):
        # Alice's 2025 meet is Division='Open'; her earlier ones are Juniors.
        res = rankings.compute_leaderboard(division="Open")
        assert {r["name"] for r in res["rows"]} == {"Alice A", "Bob B", "Carl C"}

    def test_pagination_preserves_global_rank(self, test_conn):
        page = rankings.compute_leaderboard(limit=2, offset=2)
        assert [(r["rank"], r["name"]) for r in page["rows"]] == [
            (3, "Carl C"), (4, "Dana D"),
        ]
        assert page["n_total"] == 4

    def test_limit_is_capped(self, test_conn):
        res = rankings.compute_leaderboard(limit=99999)
        assert res["limit"] == rankings.MAX_LIMIT

    def test_no_match_returns_shape_complete_empty(self, test_conn):
        res = rankings.compute_leaderboard(weight_class="120")
        assert res["rows"] == []
        assert res["n_total"] == 0
        assert res["window_start"] is not None
        assert res["metric_label"]
