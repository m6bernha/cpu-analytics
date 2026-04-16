"""DuckDB connection + Parquet registration.

Singleton connection registered against the processed Parquet files. All query
modules import `get_conn()` and run SQL through it. pandas is only used where
the downstream logic is genuinely tabular (QT coverage loop).
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

import duckdb

from .data_loader import ensure_parquets


REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OPENIPF_PARQUET = PROCESSED_DIR / "openipf.parquet"
QT_PARQUET = PROCESSED_DIR / "qt_standards.parquet"

_conn: duckdb.DuckDBPyConnection | None = None
_lock = Lock()


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return a fresh DuckDB cursor (thread-safe for concurrent queries).

    DuckDB's parent connection is not safe for concurrent .execute() calls
    from multiple threads, but .cursor() returns a per-thread child that
    shares the underlying database. We initialize the parent once (lazily)
    and hand out cursors from it.
    """
    global _conn
    if _conn is None:
        with _lock:
            if _conn is None:
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
                _conn = c
    assert _conn is not None
    return _conn.cursor()
