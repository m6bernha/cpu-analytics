"""Tests for the data_loader self-heal paths.

Covers two failure modes of assert_parquet_health (and ensure_parquets by
extension): zero-row openipf, and openipf missing one or more required
columns. Both must log, delete the local parquets so the next cold-start
re-downloads, and raise HTTPException(503).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app.data_loader import (
    REQUIRED_OPENIPF_COLUMNS,
    assert_parquet_health,
    ensure_parquets,
)


def _write_healthy_parquets(tmp_path: Path) -> tuple[Path, Path]:
    """Write a minimal parquet pair that satisfies assert_parquet_health."""
    openipf_path = tmp_path / "openipf.parquet"
    qt_path = tmp_path / "qt_standards.parquet"

    row = {col: None for col in REQUIRED_OPENIPF_COLUMNS}
    row.update(
        Name="Alice A",
        Sex="F",
        Event="SBD",
        Equipment="Raw",
        Division="Open",
        BirthYearClass="24-39",
        CanonicalWeightClass="63",
        Country="Canada",
        ParentFederation="IPF",
        Best3SquatKg=100.0,
        Best3BenchKg=60.0,
        Best3DeadliftKg=120.0,
        TotalKg=280.0,
        Goodlift=320.0,
        Date=pd.Timestamp("2025-06-01"),
    )
    pd.DataFrame([row]).to_parquet(openipf_path, index=False)
    pd.DataFrame([{"Sex": "F", "Level": "Nationals", "WeightClass": "63"}]).to_parquet(
        qt_path, index=False
    )
    return openipf_path, qt_path


def test_healthy_parquets_pass(tmp_path: Path) -> None:
    """A parquet with > 0 rows and every required column must not raise."""
    openipf_path, qt_path = _write_healthy_parquets(tmp_path)

    assert_parquet_health(openipf_path, qt_path)

    assert openipf_path.exists()
    assert qt_path.exists()


def test_zero_row_parquet_triggers_self_heal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty openipf parquet -> log, delete both files, raise 503."""
    openipf_path = tmp_path / "openipf.parquet"
    qt_path = tmp_path / "qt_standards.parquet"

    empty = pd.DataFrame({col: pd.Series(dtype="object") for col in REQUIRED_OPENIPF_COLUMNS})
    empty.to_parquet(openipf_path, index=False)
    pd.DataFrame([{"Sex": "F"}]).to_parquet(qt_path, index=False)

    with pytest.raises(HTTPException) as exc_info:
        assert_parquet_health(openipf_path, qt_path)

    assert exc_info.value.status_code == 503
    assert "zero rows" in exc_info.value.detail
    assert not openipf_path.exists()
    assert not qt_path.exists()

    captured = capsys.readouterr()
    assert "zero rows" in captured.out


def test_missing_column_triggers_self_heal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """openipf parquet missing a required column -> log, delete both, raise 503."""
    openipf_path = tmp_path / "openipf.parquet"
    qt_path = tmp_path / "qt_standards.parquet"

    partial = {col: "x" for col in REQUIRED_OPENIPF_COLUMNS if col != "Goodlift"}
    partial["TotalKg"] = 280.0
    partial["Date"] = pd.Timestamp("2025-06-01")
    pd.DataFrame([partial]).to_parquet(openipf_path, index=False)
    pd.DataFrame([{"Sex": "F"}]).to_parquet(qt_path, index=False)

    with pytest.raises(HTTPException) as exc_info:
        assert_parquet_health(openipf_path, qt_path)

    assert exc_info.value.status_code == 503
    assert "Goodlift" in exc_info.value.detail
    assert "missing required columns" in exc_info.value.detail
    assert not openipf_path.exists()
    assert not qt_path.exists()

    captured = capsys.readouterr()
    assert "Goodlift" in captured.out


def test_multiple_missing_columns_all_listed(tmp_path: Path) -> None:
    """When several required columns are absent, all of them land in the error."""
    openipf_path = tmp_path / "openipf.parquet"
    qt_path = tmp_path / "qt_standards.parquet"

    skip = {"Goodlift", "BirthYearClass", "ParentFederation"}
    partial = {col: "x" for col in REQUIRED_OPENIPF_COLUMNS if col not in skip}
    partial["TotalKg"] = 280.0
    partial["Date"] = pd.Timestamp("2025-06-01")
    pd.DataFrame([partial]).to_parquet(openipf_path, index=False)
    pd.DataFrame([{"Sex": "F"}]).to_parquet(qt_path, index=False)

    with pytest.raises(HTTPException) as exc_info:
        assert_parquet_health(openipf_path, qt_path)

    for name in skip:
        assert name in exc_info.value.detail


def test_ensure_parquets_runs_health_check_when_files_present(tmp_path: Path) -> None:
    """ensure_parquets must validate even when both files already exist."""
    openipf_path = tmp_path / "openipf.parquet"
    qt_path = tmp_path / "qt_standards.parquet"

    empty = pd.DataFrame({col: pd.Series(dtype="object") for col in REQUIRED_OPENIPF_COLUMNS})
    empty.to_parquet(openipf_path, index=False)
    pd.DataFrame([{"Sex": "F"}]).to_parquet(qt_path, index=False)

    with pytest.raises(HTTPException) as exc_info:
        ensure_parquets(openipf_path, qt_path)

    assert exc_info.value.status_code == 503
    assert not openipf_path.exists()
    assert not qt_path.exists()
