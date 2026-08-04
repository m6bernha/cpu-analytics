"""Write the synthetic test fixtures to the paths the backend reads.

Used by the CI e2e job to give Playwright a real backend without the
285 MB OpenIPF download: the same rows backend/tests/conftest.py feeds
pytest get written as real files, then uvicorn boots against them. Both
files satisfy the REQUIRED_* column checks in data_loader/qt_data_loader.

Run from the repo root:
    python scripts/make_synthetic_data.py [--force]

--force is required when the target files already exist, so a local run
cannot silently clobber a real preprocessed parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from backend.tests.conftest import _QT_CURRENT_ROWS, _QT_ROWS, _ROWS  # noqa: E402

PROCESSED = REPO_ROOT / "data" / "processed"
TARGETS = [
    PROCESSED / "openipf.parquet",
    PROCESSED / "qt_standards.parquet",
    REPO_ROOT / "data" / "qt_current.csv",
]


def main() -> int:
    force = "--force" in sys.argv[1:]
    existing = [t for t in TARGETS if t.exists()]
    if existing and not force:
        print(
            "refusing to overwrite existing data files (pass --force):\n  "
            + "\n  ".join(str(t) for t in existing)
        )
        return 1

    PROCESSED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(_ROWS).to_parquet(TARGETS[0], index=False)
    pd.DataFrame(_QT_ROWS).to_parquet(TARGETS[1], index=False)
    pd.DataFrame(_QT_CURRENT_ROWS).to_csv(TARGETS[2], index=False)
    for t in TARGETS:
        print(f"wrote {t} ({t.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
