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

from backend.app.weight_class import canonical_weight_class_bulk  # noqa: E402


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
    "Goodlift",
    "Tested",
    "Country",
    "State",
    "Federation",
    "ParentFederation",
    "Date",
    "MeetCountry",
    "MeetName",
]


def preprocess_openipf(src: Path, dst: Path, apply_scope_filter: bool = True) -> int:
    print(f"[openipf] reading {src}")
    if not src.exists():
        raise FileNotFoundError(f"OpenIPF CSV not found: {src}")

    df = pd.read_csv(src, low_memory=False, usecols=lambda c: c in KEEP_COLUMNS)

    # Fail hard on missing REQUIRED columns. A silent schema regression in
    # OpenPowerlifting's export must not publish a broken parquet.
    REQUIRED = {
        "Name", "Sex", "Event", "Equipment", "WeightClassKg", "TotalKg",
        "Date", "Country", "Federation", "ParentFederation", "MeetName",
    }
    missing_required = sorted(REQUIRED - set(df.columns))
    if missing_required:
        raise KeyError(
            f"OpenIPF CSV is missing required columns: {missing_required}. "
            f"Aborting preprocess to prevent publishing a broken parquet."
        )

    # Warn but continue for optional columns.
    missing_optional = [c for c in KEEP_COLUMNS if c not in df.columns and c not in REQUIRED]
    if missing_optional:
        print(f"[openipf] WARNING: source missing optional columns {missing_optional}")

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["TotalKg"] = pd.to_numeric(df["TotalKg"], errors="coerce")
    df["Age"] = pd.to_numeric(df.get("Age"), errors="coerce")
    df["BodyweightKg"] = pd.to_numeric(df.get("BodyweightKg"), errors="coerce")
    for c in ("Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "Goodlift"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    before = len(df)
    df = df.dropna(subset=["Date", "TotalKg", "Sex", "Name", "WeightClassKg"])
    print(f"[openipf] dropped {before - len(df)} rows missing required fields")

    # Scope filter: the app only ever serves Canadian IPF lifters (see
    # backend/app/scope.py). Filtering at preprocess time reduces the
    # parquet from ~28 MB / 1.3M rows to a small fraction, which cuts
    # backend memory pressure and per-query cost massively.
    # ParentFederation covers all IPF-sanctioned meets (CPU domestic +
    # IPF international). Country=Canada covers Canadian lifters at any
    # IPF meet, including internationals.
    # apply_scope_filter=False is opt-in for one-off backtests against
    # the full global OpenIPF dataset (e.g. About-page MAPE table).
    if apply_scope_filter:
        before = len(df)
        df = df[(df["Country"] == "Canada") & (df["ParentFederation"] == "IPF")].copy()
        print(f"[openipf] filtered to Canada+IPF: kept {len(df)} of {before} rows ({100*len(df)/before:.1f}%)")
    else:
        print(f"[openipf] scope filter SKIPPED (apply_scope_filter=False); keeping all {len(df):,} rows")

    df["Sex"] = df["Sex"].astype(str).str.upper().str.strip()
    # Vectorized canonicalization: ~30x faster than the row-wise apply on the
    # full OpenIPF export. The weekly GHA workflow benefits most.
    df["CanonicalWeightClass"] = canonical_weight_class_bulk(
        df["Sex"], df["WeightClassKg"]
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


def preprocess_athlete_projection_tables(
    openipf_parquet: Path,
    dst: Path,
) -> dict[str, int] | None:
    """Fit cohort + K-M tables against the freshly-written parquet and
    serialize them to ``dst`` as a JSON artifact.

    Shipping this alongside openipf.parquet in the data-latest release
    drops the ~27 s precompute cost off every Render cold start: the
    backend loads the artifact instead of re-fitting on boot.

    Returns the serialization stats dict, or None if fitting failed
    (non-fatal; the backend falls back to live precompute).
    """
    import duckdb

    from backend.app import athlete_projection as ap

    print(f"[proj] fitting cohort + K-M tables against {openipf_parquet}")
    conn = duckdb.connect(database=":memory:")
    try:
        conn.execute(
            f"CREATE VIEW openipf AS SELECT * FROM "
            f"parquet_scan('{openipf_parquet.as_posix()}')"
        )
        stats = ap.precompute_tables(conn)
        ap.serialize_tables(dst)
        size_kb = dst.stat().st_size / 1024.0
        print(
            f"[proj] wrote {dst} ({stats['cohort_cells']} cells, "
            f"{stats['km_tables']} km tables, {size_kb:.1f} KB)"
        )
        return stats
    except Exception as exc:  # pragma: no cover -- defensive
        print(f"[proj] WARNING: table fit failed ({exc!r}); "
              f"backend will fall back to live precompute")
        return None
    finally:
        conn.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Preprocess OpenIPF CSV + QT CSV into parquet for the app",
    )
    parser.add_argument(
        "--no-scope-filter",
        action="store_true",
        help=(
            "Skip the Country=Canada AND ParentFederation=IPF filter and "
            "write the unfiltered global parquet. Used for the About-page "
            "global-OpenIPF backtest. Default output path becomes "
            "data/processed/openipf_global.parquet, and the "
            "athlete_projection_tables artifact is skipped (scope-bound)."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Override output parquet path. Defaults to "
            "data/processed/openipf.parquet (or openipf_global.parquet "
            "with --no-scope-filter)."
        ),
    )
    args = parser.parse_args()

    openipf_csv = Path(os.environ.get("OPENIPF_CSV", DEFAULT_OPENIPF_CSV))
    qt_csv = Path(os.environ.get("QT_CSV", DEFAULT_QT_CSV))

    if args.output is not None:
        openipf_parquet = args.output
    elif args.no_scope_filter:
        openipf_parquet = PROCESSED_DIR / "openipf_global.parquet"
    else:
        openipf_parquet = PROCESSED_DIR / "openipf.parquet"

    openipf_rows = preprocess_openipf(
        openipf_csv,
        openipf_parquet,
        apply_scope_filter=not args.no_scope_filter,
    )
    qt_rows = preprocess_qt(qt_csv, PROCESSED_DIR / "qt_standards.parquet")

    if not args.no_scope_filter:
        proj_tables_path = PROCESSED_DIR / "athlete_projection_tables.json"
        proj_stats = preprocess_athlete_projection_tables(
            openipf_parquet, proj_tables_path,
        )
    else:
        proj_stats = None
        print(
            "[proj] athlete_projection_tables skipped (--no-scope-filter "
            "mode is for global backtests; tables are scoped to Canada+IPF)"
        )

    print()
    print(f"done. openipf={openipf_rows:,} rows  qt={qt_rows} rows")
    if proj_stats is not None:
        print(
            f"      athlete_projection_tables="
            f"{proj_stats['cohort_cells']} cells, "
            f"{proj_stats['km_tables']} km tables"
        )


if __name__ == "__main__":
    main()
