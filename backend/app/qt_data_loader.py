"""Runtime loader for the live-scrape qualifying-totals CSV.

In production the weekly ``qt_refresh`` GitHub Actions workflow publishes
``qt_current.csv`` to the rolling ``data-latest`` release. The backend
downloads that asset on first cold start (alongside the parquet files
handled by ``data_loader.py``).

Design decisions:
  * The scraped CSV covers 2026 onward. Historical pre-2025 / 2025
    values stay in the vendored ``data/qualifying_totals_canpl.csv``
    and its derived ``qt_standards.parquet``. The two datasets are
    independent; the frontend decides which one to query.
  * A missing ``qt_current.csv`` is not a boot-blocker. The old QT
    endpoints keep serving historical data, and the new ``/api/qt/live/*``
    endpoints degrade gracefully with ``live_data_available=false`` in
    the response meta.
  * ``QT_CURRENT_CSV_URL`` (env var) is the download URL. If unset,
    the loader looks for a local copy only — useful for local dev
    where ``python -m data.scrape_qt --dry-run --output-dir data/``
    writes ``data/qt_current.csv`` directly.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# Columns expected in qt_current.csv. If the scraper adds a new column
# we bump this list and the validation below surfaces the drift instead
# of silently ignoring it.
REQUIRED_QT_CURRENT_COLUMNS: frozenset[str] = frozenset({
    "sex", "level", "region", "division", "equipment", "event",
    "weight_class", "qt", "effective_year", "source_pdf", "fetched_at",
})


def _download(url: str, dest: Path) -> None:
    """Atomic HTTP download. Same shape as data_loader._download."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s -> %s", url, dest)
    with tempfile.NamedTemporaryFile(
        dir=dest.parent, prefix=dest.name + ".", suffix=".tmp", delete=False,
    ) as tmp_file:
        tmp_path = Path(tmp_file.name)
        with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
            shutil.copyfileobj(resp, tmp_file)
    try:
        tmp_path.replace(dest)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise
    size_kb = dest.stat().st_size / 1024
    log.info("wrote %s (%.1f KB)", dest, size_kb)


def _validate(path: Path) -> bool:
    """
    Cheap schema check on the CSV header. Returns True if the file
    contains every required column. A False return means the caller
    should treat the CSV as unavailable (most likely a first-deploy
    race before the scraper has ever published a CSV, or a corrupted
    download that we'd rather drop than serve).
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            header = f.readline().strip()
    except OSError as e:
        log.warning("qt_current.csv unreadable at %s: %s", path, e)
        return False
    cols = {c.strip() for c in header.split(",")}
    missing = sorted(REQUIRED_QT_CURRENT_COLUMNS - cols)
    if missing:
        log.warning(
            "qt_current.csv at %s missing required columns %s", path, missing,
        )
        return False
    return True


def ensure_qt_current_csv(target_path: Path) -> Path | None:
    """
    Make sure ``target_path`` exists and is valid. Returns the path on
    success or None if the live data is unavailable (in which case
    callers should fall back to ``live_data_available=false`` behaviour).

    Resolution order:
      1. If target_path exists and validates, use it.
      2. If QT_CURRENT_CSV_URL is set, download to target_path and
         validate; use if successful.
      3. Otherwise return None.
    """
    if target_path.exists() and _validate(target_path):
        log.info("qt_current.csv present at %s", target_path)
        return target_path

    url = os.environ.get("QT_CURRENT_CSV_URL")
    if not url:
        log.info(
            "no qt_current.csv at %s and QT_CURRENT_CSV_URL not set; "
            "live QT endpoints will run in degraded mode",
            target_path,
        )
        return None

    try:
        _download(url, target_path)
    except Exception as e:
        log.warning("qt_current.csv download failed from %s: %s", url, e)
        return None

    if _validate(target_path):
        return target_path
    log.warning("qt_current.csv failed validation after download; dropping")
    target_path.unlink(missing_ok=True)
    return None
