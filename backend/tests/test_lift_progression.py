"""Dedicated tests for compute_lift_progression filter semantics.

These tests mount their own synthetic parquet against DuckDB instead of
reusing the session fixture in conftest.py, because the scenarios need a
controlled mix of Equipment values and Division aliases that the shared
fixture does not provide.

Coverage:
  - Equipment="Equipped" must aggregate only Equipped rows (Single-ply,
    Multi-ply, Wraps, Unlimited) and never leak Raw rows, even when Raw
    and Equipped lifters share the same Sex/WeightClass.
  - Division="Master 1" must collapse the free-text CPU aliases
    ("Master 1", "Masters 1", "M1", "Masters 40-49") into a single
    cohort. Alias resolution lives in _build_filter_clauses, which
    compute_lift_progression calls, so the canonical label drives the
    SQL IN clause and every aliased row joins the same aggregation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from backend.app.progression import compute_lift_progression


def _meet_row(
    *,
    name: str,
    sex: str,
    equipment: str,
    division: str,
    weight_class: str,
    squat: float,
    bench: float,
    deadlift: float,
    date: str,
    age: float = 30.0,
) -> dict[str, Any]:
    """Build a single openipf row with full-SBD defaults."""
    return dict(
        Name=name,
        Sex=sex,
        Event="SBD",
        Equipment=equipment,
        Age=age,
        AgeClass="24-34",
        BirthYearClass=None,
        Division=division,
        BodyweightKg=82.0,
        WeightClassKg=weight_class,
        CanonicalWeightClass=weight_class,
        Best3SquatKg=squat,
        Best3BenchKg=bench,
        Best3DeadliftKg=deadlift,
        TotalKg=squat + bench + deadlift,
        Place="1",
        Goodlift=350.0,
        Tested="Yes",
        Country="Canada",
        State="ON",
        Federation="CPU",
        ParentFederation="IPF",
        Date=pd.Timestamp(date),
        MeetCountry="Canada",
        MeetName="Synthetic Meet",
    )


def _mount_synthetic_parquet(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Write `rows` to a parquet and swap data._base_conn to a view over it."""
    parquet_path = tmp_path / "openipf.parquet"
    pd.DataFrame(rows).to_parquet(parquet_path, index=False)

    conn = duckdb.connect(database=":memory:")
    conn.execute(
        f"CREATE VIEW openipf AS SELECT * FROM parquet_scan('{parquet_path.as_posix()}')"
    )

    import backend.app.data as data_mod
    monkeypatch.setattr(data_mod, "_base_conn", conn)


class TestEquippedAggregation:
    """Equipment="Equipped" must not mix Raw rows into the cohort."""

    def test_equipped_filter_excludes_raw_same_class_sex(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Two Raw M 83kg lifters with squat diff +20, and two Equipped M
        # 83kg lifters with squat diff +60. If the filter leaks, the mean
        # squat diff would be 40 (all four) or 20 (only Raw). With the
        # filter working, it must be 60.
        rows: list[dict[str, Any]] = [
            _meet_row(name="Raw A", sex="M", equipment="Raw",
                      division="Open", weight_class="83",
                      squat=180, bench=120, deadlift=200,
                      date="2022-01-01"),
            _meet_row(name="Raw A", sex="M", equipment="Raw",
                      division="Open", weight_class="83",
                      squat=200, bench=130, deadlift=220,
                      date="2023-01-01"),
            _meet_row(name="Raw B", sex="M", equipment="Raw",
                      division="Open", weight_class="83",
                      squat=170, bench=115, deadlift=195,
                      date="2022-01-01"),
            _meet_row(name="Raw B", sex="M", equipment="Raw",
                      division="Open", weight_class="83",
                      squat=190, bench=125, deadlift=215,
                      date="2023-01-01"),
            _meet_row(name="Eq C", sex="M", equipment="Multi-ply",
                      division="Open", weight_class="83",
                      squat=240, bench=170, deadlift=280,
                      date="2022-01-01"),
            _meet_row(name="Eq C", sex="M", equipment="Multi-ply",
                      division="Open", weight_class="83",
                      squat=300, bench=185, deadlift=310,
                      date="2023-01-01"),
            _meet_row(name="Eq D", sex="M", equipment="Single-ply",
                      division="Open", weight_class="83",
                      squat=250, bench=175, deadlift=290,
                      date="2022-01-01"),
            _meet_row(name="Eq D", sex="M", equipment="Single-ply",
                      division="Open", weight_class="83",
                      squat=310, bench=190, deadlift=320,
                      date="2023-01-01"),
        ]
        _mount_synthetic_parquet(monkeypatch, rows, tmp_path)

        result = compute_lift_progression(
            sex="M",
            equipment="Equipped",
            event="SBD",
            weight_class="83",
            country="Canada",
            parent_federation="IPF",
            x_axis="Years",
        )

        assert result["n_lifters"] == 2, (
            "Only the two Equipped lifters should survive the filter"
        )
        squat_year_1 = next(
            p for p in result["lifts"]["squat"] if p["x"] == 1
        )
        assert squat_year_1["y"] == pytest.approx(60.0), (
            "Squat diff at +1 year must be 60 (equipped-only mean), "
            "not 40 (mixed leak) or 20 (raw-only)."
        )
        assert squat_year_1["lifter_count"] == 2


class TestMaster1AliasCollapse:
    """Canonical division "Master 1" must match every free-text alias."""

    def test_master_1_canonical_matches_all_aliases(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Four lifters, each stored under a different Division alias that
        # CPU_DIVISION_ALIASES maps to canonical "Master 1". Plus one Open
        # lifter who must be filtered out.
        aliases = ["Master 1", "Masters 1", "M1", "Masters 40-49"]
        rows: list[dict[str, Any]] = []
        for idx, division in enumerate(aliases):
            name = f"M1 Lifter {idx}"
            rows.append(_meet_row(
                name=name, sex="M", equipment="Raw", division=division,
                weight_class="83", squat=200, bench=130, deadlift=220,
                date="2022-06-01", age=42.0,
            ))
            rows.append(_meet_row(
                name=name, sex="M", equipment="Raw", division=division,
                weight_class="83", squat=210, bench=135, deadlift=225,
                date="2023-06-01", age=43.0,
            ))
        rows.append(_meet_row(
            name="Open Oscar", sex="M", equipment="Raw", division="Open",
            weight_class="83", squat=205, bench=135, deadlift=225,
            date="2022-06-01", age=30.0,
        ))
        rows.append(_meet_row(
            name="Open Oscar", sex="M", equipment="Raw", division="Open",
            weight_class="83", squat=215, bench=140, deadlift=230,
            date="2023-06-01", age=31.0,
        ))
        _mount_synthetic_parquet(monkeypatch, rows, tmp_path)

        result = compute_lift_progression(
            sex="M",
            equipment="Raw",
            event="SBD",
            weight_class="83",
            division="Master 1",
            country="Canada",
            parent_federation="IPF",
            x_axis="Years",
        )

        assert result["n_lifters"] == 4, (
            "All four alias variants (Master 1, Masters 1, M1, "
            "Masters 40-49) must collapse into the Master 1 cohort. "
            "Open Oscar must be excluded."
        )
