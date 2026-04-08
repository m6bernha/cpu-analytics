"""One-shot CSV -> Parquet preprocessing for the OpenIPF dump and QT standards.

Run:
    python data/preprocess.py

Inputs (defaults, override via env vars or CLI):
    OPENIPF_CSV  -> ../openipf-2025-11-08/openipf-2025-11-08-c1c550e2.csv
    QT_CSV       -> ../openipf-2025-11-08/qualifying_totals_canpl.csv

Outputs:
    data/processed/openipf.parquet
    data/processed/qt_standards.parquet

What it does:
  * Keeps only the columns the app actually needs (drops Squat1..Bench4..etc).
  * Coerces Date and TotalKg to real types.
  * Drops rows missing Date/TotalKg/Sex/Name/WeightClassKg (unusable for the app).
  * Adds CanonicalWeightClass using backend.app.weight_class.canonical_weight_class.
  * Writes Parquet via pyarrow. No filtering on country/federation/equipment/tested
    happens here; those stay query-time knobs so the public app can serve any scope.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

# Allow importing backend.app.weight_class without a full package install.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.app.weight_class import canonical_weight_class  # noqa: E402


DATA_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = DATA_DIR / "processed"

DEFAULT_OPENIPF_CSV = (
    REPO_ROOT.parent / "openipf-2025-11-08" / "openipf-2025-11-08-c1c550e2.csv"
)
# QT standards CSV is vendored into the repo since it's a tiny hand-curated
# file (32 rows), not an external export. Lives at data/qualifying_totals_canpl.csv.
DEFAULT_QT_CSV = DATA_DIR / "qualifying_totals_canpl.csv"

KEEP_COLUMNS = [
    "Name",
    "Sex",
    "Event",
    "Equipment",
    "Age",
    "AgeClass",
    "BirthYearClass",
    "Division",
    "BodyweightKg",
    "WeightClassKg",
    "Best3SquatKg",
    "Best3BenchKg",
    "Best3DeadliftKg",
    "TotalKg",
    "Place",
    "Dots",
    "Tested",
    "Country",
    "State",
    "Federation",
    "ParentFederation",
    "Date",
    "MeetCountry",
    "MeetName",
]


def preprocess_openipf(src: Path, dst: Path) -> int:
    print(f"[openipf] reading {src}")
    if not src.exists():
        raise FileNotFoundError(f"OpenIPF CSV not found: {src}")

    df = pd.read_csv(src, low_memory=False, usecols=lambda c: c in KEEP_COLUMNS)

    missing = [c for c in KEEP_COLUMNS if c not in df.columns]
    if missing:
        print(f"[openipf] WARNING: source missing columns {missing}")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["TotalKg"] = pd.to_numeric(df["TotalKg"], errors="coerce")
    df["Age"] = pd.to_numeric(df.get("Age"), errors="coerce")
    df["BodyweightKg"] = pd.to_numeric(df.get("BodyweightKg"), errors="coerce")
    for c in ("Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "Dots"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["Date", "TotalKg", "Sex", "Name", "WeightClassKg"])
    print(f"[openipf] dropped {before - len(df)} rows missing required fields")

    df["Sex"] = df["Sex"].astype(str).str.upper().str.strip()
    df["CanonicalWeightClass"] = df.apply(
        lambda r: canonical_weight_class(r["Sex"], r["WeightClassKg"]), axis=1
    )
    before = len(df)
    df = df.dropna(subset=["CanonicalWeightClass"])
    print(f"[openipf] dropped {before - len(df)} rows with unmappable weight class")

    dst.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dst, index=False)
    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"[openipf] wrote {dst} ({len(df):,} rows, {size_mb:.1f} MB)")
    return len(df)


def preprocess_qt(src: Path, dst: Path) -> int:
    print(f"[qt] reading {src}")
    if not src.exists():
        raise FileNotFoundError(f"QT CSV not found: {src}")

    qt = pd.read_csv(src)
    required = {"Sex", "Level", "WeightClass", "QT_pre2025", "QT_2025", "QT_2027"}
    missing = required - set(qt.columns)
    if missing:
        raise ValueError(f"QT CSV missing columns: {sorted(missing)}")

    qt["Sex"] = qt["Sex"].astype(str).str.upper().str.strip()
    qt["Level"] = qt["Level"].astype(str).str.strip()
    qt["WeightClass"] = qt["WeightClass"].astype(str).str.strip()
    for c in ("QT_pre2025", "QT_2025", "QT_2027"):
        qt[c] = pd.to_numeric(qt[c], errors="coerce")

    dst.parent.mkdir(parents=True, exist_ok=True)
    qt.to_parquet(dst, index=False)
    print(f"[qt] wrote {dst} ({len(qt)} rows)")
    return len(qt)


def main() -> None:
    openipf_csv = Path(os.environ.get("OPENIPF_CSV", DEFAULT_OPENIPF_CSV))
    qt_csv = Path(os.environ.get("QT_CSV", DEFAULT_QT_CSV))

    openipf_rows = preprocess_openipf(openipf_csv, PROCESSED_DIR / "openipf.parquet")
    qt_rows = preprocess_qt(qt_csv, PROCESSED_DIR / "qt_standards.parquet")

    print()
    print(f"done. openipf={openipf_rows:,} rows  qt={qt_rows} rows")


if __name__ == "__main__":
    main()
