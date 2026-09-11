"""Tests for backend/app/qt_data_loader.py (added 2026-09-11).

This module gates whether the live QT endpoints run with data or in
degraded mode, and it had no tests while its sibling data_loader.py did.
Every network call is stubbed at ``urllib.request.urlopen``; ``time.sleep``
is stubbed so the retry path runs instantly.
"""
from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from backend.app import qt_data_loader as qdl


HEADER = ",".join(sorted(qdl.REQUIRED_QT_CURRENT_COLUMNS))
GOOD_CSV = HEADER + "\nM,Nationals,,Open,Classic,SBD,83,600.0,2026,x,y\n"


class _FakeResponse(io.BytesIO):
    """Minimal stand-in for the object urlopen returns (context manager + read)."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _stub_urlopen(monkeypatch, outcomes: list):
    """Each call pops the next outcome: bytes -> served body, Exception -> raised."""
    calls: list[str] = []

    def fake_urlopen(url, timeout=None):  # noqa: ARG001
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(qdl.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(qdl.time, "sleep", lambda _s: None)
    return calls


# --- _validate -------------------------------------------------------------

def test_validate_accepts_a_header_with_every_required_column(tmp_path: Path) -> None:
    p = tmp_path / "qt_current.csv"
    p.write_text(GOOD_CSV, encoding="utf-8")
    assert qdl._validate(p) is True


def test_validate_rejects_a_missing_column(tmp_path: Path) -> None:
    p = tmp_path / "qt_current.csv"
    cols = sorted(qdl.REQUIRED_QT_CURRENT_COLUMNS - {"effective_year"})
    p.write_text(",".join(cols) + "\n", encoding="utf-8")
    assert qdl._validate(p) is False


def test_validate_rejects_an_unreadable_path(tmp_path: Path) -> None:
    assert qdl._validate(tmp_path / "does-not-exist.csv") is False


# --- ensure_qt_current_csv -------------------------------------------------

def test_present_and_valid_file_is_used_without_any_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    p.write_text(GOOD_CSV, encoding="utf-8")
    monkeypatch.setenv("QT_CURRENT_CSV_URL", "https://example.invalid/qt.csv")
    calls = _stub_urlopen(monkeypatch, [])
    assert qdl.ensure_qt_current_csv(p) == p
    assert calls == []


def test_missing_file_and_no_url_degrades_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QT_CURRENT_CSV_URL", raising=False)
    calls = _stub_urlopen(monkeypatch, [])
    assert qdl.ensure_qt_current_csv(tmp_path / "qt_current.csv") is None
    assert calls == []


def test_missing_file_downloads_from_the_env_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    monkeypatch.setenv("QT_CURRENT_CSV_URL", "https://example.invalid/qt.csv")
    calls = _stub_urlopen(monkeypatch, [GOOD_CSV.encode()])
    assert qdl.ensure_qt_current_csv(p) == p
    assert calls == ["https://example.invalid/qt.csv"]
    assert p.read_text(encoding="utf-8") == GOOD_CSV
    # atomic write: no temp file left behind
    assert [x.name for x in tmp_path.iterdir()] == ["qt_current.csv"]


def test_downloaded_file_failing_validation_is_dropped_not_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    monkeypatch.setenv("QT_CURRENT_CSV_URL", "https://example.invalid/qt.csv")
    _stub_urlopen(monkeypatch, [b"not,a,qt,csv\n1,2,3,4\n"])
    assert qdl.ensure_qt_current_csv(p) is None
    assert not p.exists(), "a bad download must not be left for the next boot to trust"


def test_stale_present_file_that_fails_validation_is_replaced_by_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    p.write_text("old,schema\n", encoding="utf-8")
    monkeypatch.setenv("QT_CURRENT_CSV_URL", "https://example.invalid/qt.csv")
    calls = _stub_urlopen(monkeypatch, [GOOD_CSV.encode()])
    assert qdl.ensure_qt_current_csv(p) == p
    assert len(calls) == 1
    assert qdl._validate(p) is True


# --- _download retry semantics --------------------------------------------

def test_download_retries_on_503_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    err = urllib.error.HTTPError("u", 503, "unavailable", hdrs=None, fp=None)
    calls = _stub_urlopen(monkeypatch, [err, GOOD_CSV.encode()])
    qdl._download("https://example.invalid/qt.csv", p)
    assert len(calls) == 2
    assert p.read_text(encoding="utf-8") == GOOD_CSV


def test_download_does_not_retry_a_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    err = urllib.error.HTTPError("u", 404, "not found", hdrs=None, fp=None)
    calls = _stub_urlopen(monkeypatch, [err, GOOD_CSV.encode()])
    with pytest.raises(urllib.error.HTTPError):
        qdl._download("https://example.invalid/qt.csv", p)
    assert len(calls) == 1, "a 404 is not transient; retrying it is wasted time"
    assert not p.exists()


def test_download_gives_up_after_max_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "qt_current.csv"
    errs = [urllib.error.URLError("down") for _ in range(3)]
    calls = _stub_urlopen(monkeypatch, errs)
    with pytest.raises(urllib.error.URLError):
        qdl._download("https://example.invalid/qt.csv", p, max_retries=3)
    assert len(calls) == 3
    assert not p.exists()


def test_ensure_swallows_download_failure_into_degraded_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead URL must never crash boot; the live endpoints degrade instead."""
    p = tmp_path / "qt_current.csv"
    monkeypatch.setenv("QT_CURRENT_CSV_URL", "https://example.invalid/qt.csv")
    _stub_urlopen(monkeypatch, [urllib.error.URLError("down") for _ in range(3)])
    assert qdl.ensure_qt_current_csv(p) is None
