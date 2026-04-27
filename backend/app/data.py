"""DuckDB connection + Parquet registration.

A single long-lived "base" connection owns the :memory: database and the
registered parquet views. Request handlers MUST use get_cursor() (or the
with_cursor() context manager) to get a per-request cursor. DuckDB's parent
DuckDBPyConnection is NOT safe for concurrent execute() calls across threads.
Cursors share the catalog and parquet views but have independent result sets.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

import duckdb

from .data_loader import ensure_parquets
from .qt_data_loader import ensure_qt_current_csv

log = logging.getLogger(__name__)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OPENIPF_PARQUET = PROCESSED_DIR / "openipf.parquet"
QT_PARQUET = PROCESSED_DIR / "qt_standards.parquet"
# Serialized cohort + K-M artifact written by data/preprocess.py after it
# runs precompute_tables against the fresh parquet. Published alongside
# the parquet in the data-latest release. Optional: if missing or stale
# the backend falls back to live precompute on boot (~27 s).
ATHLETE_PROJ_TABLES = PROCESSED_DIR / "athlete_projection_tables.json"
# Live-scraped QT CSV (2026+). Published weekly by qt_refresh workflow
# to the data-latest release. Optional: the backend boots without it.
QT_CURRENT_CSV = REPO_ROOT / "data" / "qt_current.csv"

_base_conn: duckdb.DuckDBPyConnection | None = None
_qt_current_available: bool = False
_lock = Lock()


def _ensure_base_conn() -> duckdb.DuckDBPyConnection:
    """Lazy init of the single base connection. Called under lock."""
    global _base_conn, _qt_current_available
    if _base_conn is not None:
        return _base_conn
    with _lock:
        if _base_conn is not None:
            return _base_conn
        # Local dev: parquet is on disk from preprocess.py.
        # Production: download from GitHub Release if missing.
        ensure_parquets(OPENIPF_PARQUET, QT_PARQUET)
        c = duckdb.connect(database=":memory:")
        c.execute(
            f"CREATE VIEW openipf AS SELECT * FROM parquet_scan('{OPENIPF_PARQUET.as_posix()}')"
        )
        c.execute(
            f"CREATE VIEW qt_standards AS SELECT * FROM parquet_scan('{QT_PARQUET.as_posix()}')"
        )
        # Live-scrape CSV is optional. Register the view only if the
        # file is present and valid; otherwise the backend runs in
        # degraded mode and /api/qt/live/* endpoints report
        # live_data_available=false.
        live_path = ensure_qt_current_csv(QT_CURRENT_CSV)
        if live_path is not None:
            try:
                c.execute(
                    "CREATE VIEW qt_current AS "
                    f"SELECT * FROM read_csv_auto('{live_path.as_posix()}', header=True)"
                )
                _qt_current_available = True
                log.info("qt_current view registered from %s", live_path)
            except duckdb.Error as e:
                _qt_current_available = False
                log.warning(
                    "qt_current view registration skipped: duckdb_error: %s",
                    e,
                )
        else:
            _qt_current_available = False
            # Surface a one-line summary at WARN so operators see this
            # in Render boot logs without grepping. The detailed reason
            # (download failed / validation failed / URL unset) is
            # already logged by ensure_qt_current_csv at the appropriate
            # level just above this branch.
            reason = (
                "url_unset"
                if not os.environ.get("QT_CURRENT_CSV_URL")
                else "download_or_validation_failed"
            )
            log.warning(
                "qt_current view registration skipped: %s "
                "(see prior log lines for details). Live QT endpoints "
                "will run in degraded mode.",
                reason,
            )
        _base_conn = c
    return _base_conn


def is_qt_current_available() -> bool:
    """True if the live-scraped qt_current view was successfully registered."""
    _ensure_base_conn()
    return _qt_current_available


def get_cursor() -> duckdb.DuckDBPyConnection:
    """Return a fresh cursor for a single request.

    Each request handler should call this at the top of the function and
    use the returned cursor for all its queries. Cursors are released on
    garbage collection; do not close them manually or pass them between
    requests.
    """
    base = _ensure_base_conn()
    return base.cursor()


@contextmanager
def with_cursor() -> Iterator[duckdb.DuckDBPyConnection]:
    """Context manager wrapper around get_cursor() for readability."""
    cur = get_cursor()
    try:
        yield cur
    finally:
        # Cursor close is a no-op if already closed; explicit close
        # releases any open result set immediately rather than waiting
        # for garbage collection.
        try:
            cur.close()
        except Exception:
            pass


def get_conn() -> duckdb.DuckDBPyConnection:
    """DEPRECATED: use get_cursor() or with_cursor() instead.

    Kept for backwards compatibility with existing call sites.
    """
    return get_cursor()
