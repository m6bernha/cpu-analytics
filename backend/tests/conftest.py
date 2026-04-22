"""Shared test fixtures for backend tests.

Creates a tiny synthetic parquet pair (openipf + qt_standards) in a temp
directory, then monkey-patches the DuckDB singleton so all query modules
read from the fixture instead of the real data.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# ---------------------------------------------------------------------------
# Synthetic lifters
# ---------------------------------------------------------------------------
# We build a small but representative dataset that covers:
#   - A lifter with meets in both Junior and Open age ranges (age transition)
#   - A lifter with a 3-year gap between meets (comeback)
#   - A lifter with only 1 meet (should be excluded from progression)
#   - A lifter with a bench-only meet (non-SBD event)
#   - Multiple weight classes and sexes
# ---------------------------------------------------------------------------

_ROWS = [
    # -- Alice: Junior->Open transition. 3 SBD meets. Ages 22, 23, 25.
    dict(Name="Alice A", Sex="F", Event="SBD", Equipment="Raw", Age=22.0,
         AgeClass="20-23", BirthYearClass=None, Division="Juniors",
         BodyweightKg=62.0, WeightClassKg="63", CanonicalWeightClass="63",
         Best3SquatKg=100, Best3BenchKg=60, Best3DeadliftKg=120, TotalKg=280,
         Place="1", Goodlift=320.0, Tested="Yes", Country="Canada", State="ON",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2022-06-01"), MeetCountry="Canada",
         MeetName="Ontario Champs"),
    dict(Name="Alice A", Sex="F", Event="SBD", Equipment="Raw", Age=23.0,
         AgeClass="20-23", BirthYearClass=None, Division="Juniors",
         BodyweightKg=62.5, WeightClassKg="63", CanonicalWeightClass="63",
         Best3SquatKg=110, Best3BenchKg=65, Best3DeadliftKg=130, TotalKg=305,
         Place="1", Goodlift=345.0, Tested="Yes", Country="Canada", State="ON",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2023-06-01"), MeetCountry="Canada",
         MeetName="Ontario Champs"),
    dict(Name="Alice A", Sex="F", Event="SBD", Equipment="Raw", Age=25.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=63.0, WeightClassKg="63", CanonicalWeightClass="63",
         Best3SquatKg=120, Best3BenchKg=70, Best3DeadliftKg=140, TotalKg=330,
         Place="1", Goodlift=370.0, Tested="Yes", Country="Canada", State="ON",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2025-06-01"), MeetCountry="Canada",
         MeetName="Ontario Champs"),

    # -- Bob: steady Open lifter. 4 SBD meets over 3 years. All Open.
    dict(Name="Bob B", Sex="M", Event="SBD", Equipment="Raw", Age=28.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=82.0, WeightClassKg="83", CanonicalWeightClass="83",
         Best3SquatKg=180, Best3BenchKg=120, Best3DeadliftKg=200, TotalKg=500,
         Place="1", Goodlift=350.0, Tested="Yes", Country="Canada", State="BC",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2022-01-15"), MeetCountry="Canada",
         MeetName="BC Open"),
    dict(Name="Bob B", Sex="M", Event="SBD", Equipment="Raw", Age=29.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=82.5, WeightClassKg="83", CanonicalWeightClass="83",
         Best3SquatKg=190, Best3BenchKg=125, Best3DeadliftKg=210, TotalKg=525,
         Place="1", Goodlift=365.0, Tested="Yes", Country="Canada", State="BC",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2023-01-15"), MeetCountry="Canada",
         MeetName="BC Open"),
    dict(Name="Bob B", Sex="M", Event="SBD", Equipment="Raw", Age=30.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=83.0, WeightClassKg="83", CanonicalWeightClass="83",
         Best3SquatKg=200, Best3BenchKg=130, Best3DeadliftKg=220, TotalKg=550,
         Place="1", Goodlift=380.0, Tested="Yes", Country="Canada", State="BC",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2024-01-15"), MeetCountry="Canada",
         MeetName="BC Open"),
    dict(Name="Bob B", Sex="M", Event="SBD", Equipment="Raw", Age=31.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=83.0, WeightClassKg="83", CanonicalWeightClass="83",
         Best3SquatKg=205, Best3BenchKg=135, Best3DeadliftKg=225, TotalKg=565,
         Place="1", Goodlift=390.0, Tested="Yes", Country="Canada", State="BC",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2025-01-15"), MeetCountry="Canada",
         MeetName="BC Open"),

    # -- Carl: comeback lifter. 2 meets, 4 years apart.
    dict(Name="Carl C", Sex="M", Event="SBD", Equipment="Raw", Age=25.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=92.0, WeightClassKg="93", CanonicalWeightClass="93",
         Best3SquatKg=170, Best3BenchKg=110, Best3DeadliftKg=190, TotalKg=470,
         Place="2", Goodlift=300.0, Tested="Yes", Country="Canada", State="AB",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2020-03-01"), MeetCountry="Canada",
         MeetName="Alberta Open"),
    dict(Name="Carl C", Sex="M", Event="SBD", Equipment="Raw", Age=29.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=93.0, WeightClassKg="93", CanonicalWeightClass="93",
         Best3SquatKg=220, Best3BenchKg=140, Best3DeadliftKg=240, TotalKg=600,
         Place="1", Goodlift=370.0, Tested="Yes", Country="Canada", State="AB",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2024-03-01"), MeetCountry="Canada",
         MeetName="Alberta Open"),

    # -- Dana: single-meet lifter (should be excluded from progression).
    dict(Name="Dana D", Sex="F", Event="SBD", Equipment="Raw", Age=20.0,
         AgeClass="20-23", BirthYearClass=None, Division="Juniors",
         BodyweightKg=56.0, WeightClassKg="57", CanonicalWeightClass="57",
         Best3SquatKg=80, Best3BenchKg=45, Best3DeadliftKg=100, TotalKg=225,
         Place="3", Goodlift=290.0, Tested="Yes", Country="Canada", State="QC",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2024-09-01"), MeetCountry="Canada",
         MeetName="Quebec Classic"),

    # -- Ella: female Multi-ply Open lifter who changes weight class (72 -> 84).
    # Used to verify same_class_only filtering and Equipment="Equipped" matching
    # for the per-lift progression endpoint. Sex=F + Equipment=Multi-ply keeps
    # her out of every existing test (which all filter equipment="Raw" or
    # sex="M" with equipment="Single-ply").
    dict(Name="Ella E", Sex="F", Event="SBD", Equipment="Multi-ply", Age=30.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=71.0, WeightClassKg="72", CanonicalWeightClass="72",
         Best3SquatKg=160, Best3BenchKg=100, Best3DeadliftKg=180, TotalKg=440,
         Place="1", Goodlift=300.0, Tested="Yes", Country="Canada", State="ON",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2023-05-01"), MeetCountry="Canada",
         MeetName="Ontario Equipped"),
    dict(Name="Ella E", Sex="F", Event="SBD", Equipment="Multi-ply", Age=31.0,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=82.0, WeightClassKg="84", CanonicalWeightClass="84",
         Best3SquatKg=180, Best3BenchKg=115, Best3DeadliftKg=200, TotalKg=495,
         Place="1", Goodlift=335.0, Tested="Yes", Country="Canada", State="ON",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2024-05-01"), MeetCountry="Canada",
         MeetName="Ontario Equipped"),

    # -- Bob's bench-only meet (non-SBD event).
    dict(Name="Bob B", Sex="M", Event="B", Equipment="Raw", Age=29.5,
         AgeClass="24-34", BirthYearClass=None, Division="Open",
         BodyweightKg=82.5, WeightClassKg="83", CanonicalWeightClass="83",
         Best3SquatKg=None, Best3BenchKg=135, Best3DeadliftKg=None, TotalKg=135,
         Place="1", Goodlift=120.0, Tested="Yes", Country="Canada", State="BC",
         Federation="CPU", ParentFederation="IPF",
         Date=pd.Timestamp("2023-06-01"), MeetCountry="Canada",
         MeetName="BC Bench Bash"),
]

_QT_ROWS = [
    dict(Sex="M", Level="Nationals", WeightClass="83", QT_pre2025=625, QT_2025=687.5, QT_2027=700),
    dict(Sex="M", Level="Regionals", WeightClass="83", QT_pre2025=535, QT_2025=535, QT_2027=630),
    dict(Sex="M", Level="Nationals", WeightClass="93", QT_pre2025=665, QT_2025=710, QT_2027=732.5),
    dict(Sex="M", Level="Regionals", WeightClass="93", QT_pre2025=567.5, QT_2025=567.5, QT_2027=660),
    dict(Sex="F", Level="Nationals", WeightClass="63", QT_pre2025=347.5, QT_2025=375, QT_2027=390),
    dict(Sex="F", Level="Regionals", WeightClass="63", QT_pre2025=302.5, QT_2025=302.5, QT_2027=350),
    dict(Sex="F", Level="Nationals", WeightClass="57", QT_pre2025=320, QT_2025=340, QT_2027=355),
    dict(Sex="F", Level="Regionals", WeightClass="57", QT_pre2025=280, QT_2025=280, QT_2027=320),
]


# ---------------------------------------------------------------------------
# Synthetic qt_current rows for live-scrape tests.
# Small subset: Open + Junior, Men + Women, Nationals + Regionals, 2026 +
# 2027 with regional split in 2027. Values picked to exercise the coverage
# math against the synthetic lifter rows above.
# ---------------------------------------------------------------------------

_QT_CURRENT_ROWS = [
    # 2026 Nationals (pre regional split -> region NULL)
    dict(sex="M", level="Nationals", region=None, division="Open",
         equipment="Classic", event="SBD", weight_class="83",
         qt=500.0, effective_year=2026,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
    dict(sex="F", level="Nationals", region=None, division="Open",
         equipment="Classic", event="SBD", weight_class="63",
         qt=320.0, effective_year=2026,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
    # 2026 Regionals (no split)
    dict(sex="M", level="Regionals", region=None, division="Open",
         equipment="Classic", event="SBD", weight_class="83",
         qt=450.0, effective_year=2026,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
    # 2027 Nationals (region still NULL -- no regional split at Nationals
    # level).
    dict(sex="M", level="Nationals", region=None, division="Open",
         equipment="Classic", event="SBD", weight_class="83",
         qt=525.0, effective_year=2027,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
    # 2027 Regionals -- Western/Central
    dict(sex="M", level="Regionals", region="Western/Central",
         division="Open", equipment="Classic", event="SBD",
         weight_class="83", qt=475.0, effective_year=2027,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
    # 2027 Regionals -- Eastern
    dict(sex="M", level="Regionals", region="Eastern",
         division="Open", equipment="Classic", event="SBD",
         weight_class="83", qt=460.0, effective_year=2027,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
    # Age division other than Open (Junior) to exercise division filter.
    dict(sex="F", level="Nationals", region=None, division="Junior",
         equipment="Classic", event="SBD", weight_class="63",
         qt=280.0, effective_year=2026,
         source_pdf="test", fetched_at="2026-04-21T00:00:00+00:00"),
]


@pytest.fixture(scope="session")
def test_parquets(tmp_path_factory):
    """Write synthetic parquet files and return their paths."""
    d = tmp_path_factory.mktemp("data")
    openipf_path = d / "openipf.parquet"
    qt_path = d / "qt_standards.parquet"
    qt_current_path = d / "qt_current.csv"

    df = pd.DataFrame(_ROWS)
    df.to_parquet(openipf_path, index=False)

    qt = pd.DataFrame(_QT_ROWS)
    qt.to_parquet(qt_path, index=False)

    # qt_current is CSV (matches production shape).
    pd.DataFrame(_QT_CURRENT_ROWS).to_csv(qt_current_path, index=False)

    return openipf_path, qt_path, qt_current_path


@pytest.fixture(scope="session")
def test_conn(test_parquets):
    """Create a DuckDB connection against the synthetic parquets.

    Monkey-patches backend.app.data so all modules that call get_conn()
    use this connection for the entire test session.
    """
    openipf_path, qt_path, qt_current_path = test_parquets

    conn = duckdb.connect(database=":memory:")
    conn.execute(
        f"CREATE VIEW openipf AS SELECT * FROM parquet_scan('{openipf_path.as_posix()}')"
    )
    conn.execute(
        f"CREATE VIEW qt_standards AS SELECT * FROM parquet_scan('{qt_path.as_posix()}')"
    )
    conn.execute(
        "CREATE VIEW qt_current AS "
        f"SELECT * FROM read_csv_auto('{qt_current_path.as_posix()}', header=True)"
    )

    # Monkey-patch the singleton base connection so get_cursor() returns
    # cursors against the synthetic parquets instead of downloading real data.
    # Also flip the live-data flag so is_qt_current_available() reports True.
    import backend.app.data as data_mod
    data_mod._base_conn = conn
    data_mod._qt_current_available = True

    return conn
