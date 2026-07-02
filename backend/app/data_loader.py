"""Runtime parquet loader for production deploys.

In local dev, `python data/preprocess.py` writes the parquet files into
data/processed/ and the backend reads them directly. In production (Render),
the container has writable local storage but is rebuilt on every deploy, so
the parquet files are downloaded on first startup from a GitHub Release
asset built by .github/workflows/refresh-data.yml.

Env vars:
    OPENIPF_PARQUET_URL         - direct download URL for openipf.parquet
    QT_PARQUET_URL              - direct download URL for qt_standards.parquet
    ATHLETE_PROJ_TABLES_URL     - direct download URL for the Athlete
                                  Projection cohort + K-M artifact
                                  (athlete_projection_tables.json).
                                  Optional; if missing, the backend falls
                                  back to live precompute on boot.

If both parquets already exist locally, no download happens. If they're
missing and the URLs aren't set, we raise a clear error pointing the
developer at either preprocess.py or the env vars.

Self-heal: after download (or on cold start with files already present), we
validate that openipf has >0 rows AND every required column. On failure we
delete the local parquets so the next cold-start re-downloads, and raise a
503 so the in-flight request gets a user-safe error.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)


REQUIRED_OPENIPF_COLUMNS: frozenset[str] = frozenset(
    {
        "Date",
        "Name",
        "Sex",
        "CanonicalWeightClass",
        "Equipment",
        "Event",
        "Best3SquatKg",
        "Best3BenchKg",
        "Best3DeadliftKg",
        "TotalKg",
        "Goodlift",
        "Country",
        "ParentFederation",
        "Division",
        "BirthYearClass",
    }
)


def _download(url: str, dest: Path, max_retries: int = 3) -> None:
    """Download URL to dest atomically via a unique temp file.

    Using a process-unique temp name prevents concurrent cold-start
    downloads from stomping each other's partial writes.

    Retries up to max_retries times with exponential backoff on URLError,
    HTTPError 429/5xx, timeout, or connection reset.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("[data_loader] downloading %s -> %s", url, dest)

    backoff_secs = [2, 8]  # exponential backoff: 2s, then 8s
    last_exc = None

    for attempt in range(max_retries):
        try:
            # NamedTemporaryFile with delete=False gives us a unique path on the
            # same filesystem; rename is atomic on Linux/macOS and best-effort on Windows.
            with tempfile.NamedTemporaryFile(
                dir=dest.parent, prefix=dest.name + ".", suffix=".tmp", delete=False
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                with urllib.request.urlopen(url, timeout=120) as resp:
                    shutil.copyfileobj(resp, tmp_file)
            try:
                tmp_path.replace(dest)
            except OSError:
                # Cleanup on failure
                tmp_path.unlink(missing_ok=True)
                raise
            size_mb = dest.stat().st_size / (1024 * 1024)
            log.info("[data_loader] wrote %s (%.1f MB)", dest, size_mb)
            return
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            ConnectionResetError,
        ) as exc:
            last_exc = exc
            is_retryable = (
                isinstance(exc, urllib.error.HTTPError)
                and exc.code in (429, 500, 502, 503, 504)
            ) or isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionResetError))
            if not is_retryable or attempt >= max_retries - 1:
                raise
            wait_secs = backoff_secs[min(attempt, len(backoff_secs) - 1)]
            log.warning(
                "[data_loader] download attempt %d/%d failed (%s), retrying in %.0f seconds",
                attempt + 1, max_retries, type(exc).__name__, wait_secs
            )
            time.sleep(wait_secs)


def _gc_after() -> None:
    """Release transient buffers accumulated during downloads."""
    import gc
    gc.collect()


def assert_parquet_health(openipf_path: Path, qt_path: Path) -> None:
    """Validate parquets are usable; trigger self-heal and 503 on failure.

    Checks:
      1. openipf has > 0 rows
      2. openipf contains every REQUIRED_OPENIPF_COLUMNS entry

    On failure: logs the specific problem, deletes BOTH local parquets so the
    next cold-start re-downloads them from the GitHub Release, and raises
    HTTPException(503). Called from ensure_parquets() so every cold-start
    validates, whether the files were just downloaded or already on disk.
    """
    import duckdb
    from fastapi import HTTPException

    conn = duckdb.connect(database=":memory:")
    try:
        row_count: int = conn.execute(
            f"SELECT COUNT(*) FROM parquet_scan('{openipf_path.as_posix()}')"
        ).fetchone()[0]
        columns: set[str] = {
            r[0]
            for r in conn.execute(
                f"DESCRIBE SELECT * FROM parquet_scan('{openipf_path.as_posix()}')"
            ).fetchall()
        }
    finally:
        conn.close()

    problem: str | None = None
    if row_count == 0:
        problem = "openipf parquet has zero rows"
    else:
        missing = sorted(REQUIRED_OPENIPF_COLUMNS - columns)
        if missing:
            problem = f"openipf parquet missing required columns: {missing}"

    if problem is None:
        return

    log.error(
        "[data_loader] %s. Removing local parquets to trigger re-download on next cold-start.",
        problem
    )
    openipf_path.unlink(missing_ok=True)
    qt_path.unlink(missing_ok=True)
    raise HTTPException(
        status_code=503,
        detail=f"Data not ready: {problem}. Please retry in a moment.",
    )


def ensure_athlete_proj_tables(tables_path: Path) -> bool:
    """Best-effort fetch of the serialized Athlete Projection artifact.

    Returns True iff the artifact is present on disk after this call.
    Never raises: download failure or missing URL is a soft miss and
    the lifespan falls back to live precompute (~27 s). This is a cold-
    start optimisation, not a correctness requirement.
    """
    if tables_path.exists():
        return True
    url = os.environ.get("ATHLETE_PROJ_TABLES_URL")
    if not url:
        return False
    try:
        _download(url, tables_path)
    except Exception as exc:  # pragma: no cover -- defensive
        log.warning(
            "[data_loader] athlete_proj_tables download failed: %r "
            "(falling back to live precompute)",
            exc
        )
        return False
    return tables_path.exists()


def ensure_parquets(openipf_path: Path, qt_path: Path) -> None:
    """Ensure both parquet files exist locally, downloading if necessary.

    Raises FileNotFoundError with a clear message if the files are missing
    and no download URL is configured. Raises HTTPException(503) via
    assert_parquet_health if the loaded parquet is empty or missing
    required columns.
    """
    needs_openipf = not openipf_path.exists()
    needs_qt = not qt_path.exists()

    if needs_openipf or needs_qt:
        openipf_url = os.environ.get("OPENIPF_PARQUET_URL")
        qt_url = os.environ.get("QT_PARQUET_URL")

        if needs_openipf:
            if not openipf_url:
                raise FileNotFoundError(
                    f"openipf.parquet not found at {openipf_path} and "
                    f"OPENIPF_PARQUET_URL env var is not set. "
                    f"Run `python data/preprocess.py` for local dev, or set "
                    f"OPENIPF_PARQUET_URL to a GitHub Release asset URL for production."
                )
            _download(openipf_url, openipf_path)

        if needs_qt:
            if not qt_url:
                raise FileNotFoundError(
                    f"qt_standards.parquet not found at {qt_path} and "
                    f"QT_PARQUET_URL env var is not set."
                )
            _download(qt_url, qt_path)

        # Release any transient buffers from the downloads before the caller
        # builds the DuckDB connection. Matters on the 512 MB Render tier.
        _gc_after()

    # Validate whether the file was just downloaded OR was already on disk.
    # A stale/corrupt parquet that survived a previous deploy must still
    # trigger self-heal.
    assert_parquet_health(openipf_path, qt_path)
