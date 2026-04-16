"""DuckDB connection + Parquet registration.

A single long-lived "base" connection owns the :memory: database and the
registered parquet views. Request handlers MUST use get_cursor() (or the
with_cursor() context manager) to get a per-request cursor. DuckDB's parent
DuckDBPyConnection is NOT safe for concurrent execute() calls across threads.
Cursors share the catalog and parquet views but have independent result sets.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Iterator

import duckdb

from .data_loader import ensure_parquets


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OPENIPF_PARQUET = PROCESSED_DIR / "openipf.parquet"
QT_PARQUET = PROCESSED_DIR / "qt_standards.parquet"

_base_conn: duckdb.DuckDBPyConnection | None = None
_lock = Lock()


def _ensure_base_conn() -> duckdb.DuckDBPyConnection:
    """Lazy init of the single base connection. Called under lock."""
    global _base_conn
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
        _base_conn = c
    return _base_conn


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
