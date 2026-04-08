"""Runtime parquet loader for production deploys.

In local dev, `python data/preprocess.py` writes the parquet files into
data/processed/ and the backend reads them directly. In production (Fly.io),
the container is ephemeral and there's no preprocess step at startup. Instead,
the parquet files are downloaded once on first request from a GitHub Release
asset built by .github/workflows/refresh-data.yml.

Env vars:
    OPENIPF_PARQUET_URL   — direct download URL for openipf.parquet
    QT_PARQUET_URL        — direct download URL for qt_standards.parquet

If both files already exist locally, no download happens. If they're missing
and the URLs aren't set, we raise a clear error pointing the developer at
either preprocess.py or the env vars.
"""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    print(f"[data_loader] downloading {url} -> {dest}")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"[data_loader] wrote {dest} ({size_mb:.1f} MB)")


def ensure_parquets(openipf_path: Path, qt_path: Path) -> None:
    """Ensure both parquet files exist locally, downloading if necessary.

    Raises FileNotFoundError with a clear message if the files are missing
    and no download URL is configured.
    """
    needs_openipf = not openipf_path.exists()
    needs_qt = not qt_path.exists()

    if not needs_openipf and not needs_qt:
        return

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
