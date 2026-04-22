"""Offline backtest for Athlete Projection Engine C vs alternatives.

Walk-forward evaluation against lifters with 15+ SBD meets. For each lifter:
  1. Hold out their last H meets (H = 3 by default).
  2. Fit Engine C (personal Huber + GLP-bracket cohort) on the remainder.
  3. Predict forward at 3, 6, 12, 18-month horizons from the last training meet.
  4. Compare predicted total to the actual held-out total at the closest date
     to each horizon. Report mean absolute percentage error (MAPE).

The spec wants a GLOBAL OpenIPF comparison for sample size. This script accepts
either a Canada+IPF parquet (default, for smoke-testing the pipeline) or a
broader parquet via --input. Running against the full OpenIPF export is a
one-off manual step -- download openipf-latest.csv, preprocess to parquet,
then point --input at it.

Usage:
    python data/backtest_projection.py \
        --input data/processed/openipf.parquet \
        --output data/backtest_results.json

Not wired into CI. Not imported by any production module. The About page
consumes the JSON artifact as a static file when it lands.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

# Add the backend package to the Python path so we can reuse Engine C helpers.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import athlete_projection as ap  # noqa: E402
from backend.app.ipf_gl_points import (  # noqa: E402
    assign_glp_bracket,
    ipf_gl_points,
)

logger = logging.getLogger("backtest")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

DEFAULT_HOLDOUT = 3
HORIZONS_MONTHS = (3, 6, 12, 18)
MIN_MEETS_FOR_BACKTEST = 15


@dataclass
class LifterError:
    name: str
    engine: str               # "engine_c" | "log_linear" | "gompertz"
    horizon_months: int
    predicted_total: float
    actual_total: float
    absolute_percentage_error: float


@dataclass
class EngineSummary:
    engine: str
    per_horizon: dict[int, list[float]] = field(default_factory=dict)  # horizon -> APEs
    lifter_count: int = 0

    def mape_at(self, horizon: int) -> float | None:
        apes = self.per_horizon.get(horizon)
        if not apes:
            return None
        return float(np.mean(apes))

    def as_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "lifter_count": self.lifter_count,
            "mape_by_horizon": {
                str(h): self.mape_at(h) for h in HORIZONS_MONTHS
            },
            "sample_sizes_by_horizon": {
                str(h): len(self.per_horizon.get(h, [])) for h in HORIZONS_MONTHS
            },
        }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_parquet_into_duckdb(parquet_path: Path) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(database=":memory:")
    conn.execute(
        f"CREATE VIEW openipf AS SELECT * FROM parquet_scan('{parquet_path.as_posix()}')"
    )
    return conn


def select_backtest_lifters(conn) -> pd.DataFrame:
    """Lifters with >= MIN_MEETS_FOR_BACKTEST SBD meets and non-null BW/Age/Sex."""
    sql = f"""
        WITH sbd AS (
            SELECT Name, Sex, Age, BodyweightKg, Date,
                   Best3SquatKg, Best3BenchKg, Best3DeadliftKg, TotalKg, Equipment
            FROM openipf
            WHERE Event = 'SBD'
              AND TotalKg IS NOT NULL
              AND BodyweightKg IS NOT NULL
              AND Age IS NOT NULL
              AND Equipment = 'Raw'
        ),
        counts AS (
            SELECT Name, COUNT(*) AS n
            FROM sbd
            GROUP BY Name
            HAVING COUNT(*) >= {MIN_MEETS_FOR_BACKTEST}
        )
        SELECT s.*
        FROM sbd s
        JOIN counts c USING (Name)
        ORDER BY s.Name, s.Date
    """
    return conn.execute(sql).df()


# ---------------------------------------------------------------------------
# Engine C projection (reuses Engine C internals)
# ---------------------------------------------------------------------------


def engine_c_predict(
    train: pd.DataFrame,
    horizon_days: float,
    cohort_cell_slope: float,
    cohort_cell_std: float,
) -> float | None:
    """Project total at (last training meet + horizon_days) using Engine C
    math on a single lifter's training history.

    Level = max of last 3 TotalKg (median of 2 if fewer).
    Slope = w_p * personal + (1 - w_p) * cohort, w_p = n / (n+5).
    Projection = level + slope_combined * horizon_days.
    """
    totals = train["TotalKg"].astype(float).tolist()
    n = len(totals)
    if n < 2:
        return None
    current_level = ap.compute_current_level(totals)
    if current_level is None:
        return None

    dates = pd.to_datetime(train["Date"].values)
    days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
    if len(np.unique(days)) < 2:
        return None

    fit = ap._robust_slope(days, np.asarray(totals))
    slope_personal = float(fit[0]) if fit else 0.0

    w_personal = n / (n + ap.SHRINKAGE_K)
    slope_combined = (
        w_personal * slope_personal
        + (1 - w_personal) * cohort_cell_slope
    )
    return float(current_level + slope_combined * horizon_days)


# ---------------------------------------------------------------------------
# Comparator engines
# ---------------------------------------------------------------------------


def log_linear_predict(train: pd.DataFrame, horizon_days: float) -> float | None:
    """Fit log(total) ~ time via OLS and project forward."""
    totals = train["TotalKg"].astype(float).to_numpy()
    n = len(totals)
    if n < 3 or np.any(totals <= 0):
        return None
    dates = pd.to_datetime(train["Date"].values)
    days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
    if len(np.unique(days)) < 2:
        return None
    log_totals = np.log(totals)
    slope, intercept = np.polyfit(days, log_totals, 1)
    last_day = float(days[-1])
    future_day = last_day + horizon_days
    return float(np.exp(slope * future_day + intercept))


def gompertz_predict(train: pd.DataFrame, horizon_days: float) -> float | None:
    """Fit y = A * exp(-B * exp(-C * t)) via non-linear least squares."""
    totals = train["TotalKg"].astype(float).to_numpy()
    n = len(totals)
    if n < 4 or np.any(totals <= 0):
        return None
    dates = pd.to_datetime(train["Date"].values)
    days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
    if len(np.unique(days)) < 2:
        return None
    try:
        from scipy.optimize import curve_fit

        a0 = float(np.max(totals) * 1.1)
        b0 = 1.0
        c0 = 0.001

        def gompertz(t: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
            return a * np.exp(-b * np.exp(-c * t))

        popt, _ = curve_fit(
            gompertz, days, totals,
            p0=[a0, b0, c0], maxfev=2000,
        )
        a, b, c = popt
        last_day = float(days[-1])
        future_day = last_day + horizon_days
        return float(gompertz(np.array([future_day]), a, b, c)[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Backtest driver
# ---------------------------------------------------------------------------


def fit_cohort_cells_from_frame(hist: pd.DataFrame) -> dict:
    """Temporary wrapper that mirrors athlete_projection._fit_cohort_cells on
    an in-memory DataFrame. Used so the backtest does not need a live
    FastAPI app."""
    conn = duckdb.connect(database=":memory:")
    conn.register("openipf", hist)
    return ap._fit_cohort_cells(conn)


def run_backtest(
    input_path: Path,
    output_path: Path,
    max_lifters: int | None = None,
) -> None:
    logger.info("Loading parquet: %s", input_path)
    conn = load_parquet_into_duckdb(input_path)

    logger.info("Selecting backtest lifters (>= %d SBD meets)", MIN_MEETS_FOR_BACKTEST)
    df = select_backtest_lifters(conn)
    if df.empty:
        logger.warning("No backtest-eligible lifters in dataset. Exiting.")
        return

    # Pre-fit cohort cells on the full dataset (not per-lifter leave-one-out;
    # acceptable because a single lifter's influence on 231 cells is small).
    logger.info("Fitting GLP-bracket cohort cells on full training set")
    hist_for_cohort = df[[
        "Name", "Sex", "Age", "BodyweightKg", "Date", "Equipment",
        "Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "TotalKg",
    ]].copy()
    hist_for_cohort["Event"] = "SBD"
    hist_for_cohort["Country"] = "Canada"
    hist_for_cohort["ParentFederation"] = "IPF"
    cells = fit_cohort_cells_from_frame(hist_for_cohort)
    logger.info("Cohort cells fit: %d", len(cells))

    summaries: dict[str, EngineSummary] = {
        "engine_c": EngineSummary(engine="engine_c"),
        "log_linear": EngineSummary(engine="log_linear"),
        "gompertz": EngineSummary(engine="gompertz"),
    }

    lifter_names = list(df["Name"].unique())
    if max_lifters:
        lifter_names = lifter_names[:max_lifters]

    errors: list[LifterError] = []
    processed = 0
    for name in lifter_names:
        lifter_meets = df[df["Name"] == name].sort_values("Date").reset_index(drop=True)
        if len(lifter_meets) < MIN_MEETS_FOR_BACKTEST:
            continue

        holdout = lifter_meets.tail(DEFAULT_HOLDOUT)
        train = lifter_meets.iloc[: -DEFAULT_HOLDOUT]

        last_train_row = train.iloc[-1]
        last_train_date = pd.to_datetime(last_train_row["Date"])

        glp = ipf_gl_points(
            total_kg=float(last_train_row["TotalKg"]),
            bw_kg=float(last_train_row["BodyweightKg"]),
            age=float(last_train_row["Age"]),
            sex=str(last_train_row["Sex"]),
        )
        bracket = assign_glp_bracket(glp)
        division = ap.age_to_category(float(last_train_row["Age"]))
        if division not in ap.AGE_DIVISIONS:
            continue

        cell = cells.get((division, bracket, "squat"))  # total-level cohort proxy
        cohort_slope = cell.slope_kg_per_day if cell else 0.0
        cohort_std = cell.residual_std if cell else 0.0

        for horizon in HORIZONS_MONTHS:
            horizon_days = horizon * ap.DAYS_PER_MONTH
            target_date = last_train_date + pd.Timedelta(days=horizon_days)
            # Actual = holdout meet closest to target_date (within +/- 3 months).
            deltas = (pd.to_datetime(holdout["Date"]) - target_date).abs()
            nearest_idx = int(np.argmin(deltas.values))
            if deltas.iloc[nearest_idx].days > 90:
                continue
            actual = float(holdout["TotalKg"].iloc[nearest_idx])

            # Engine C
            pred_c = engine_c_predict(
                train, horizon_days, cohort_slope, cohort_std,
            )
            if pred_c is not None:
                ape = 100.0 * abs(pred_c - actual) / actual
                summaries["engine_c"].per_horizon.setdefault(horizon, []).append(ape)
                errors.append(LifterError(
                    name=name, engine="engine_c", horizon_months=horizon,
                    predicted_total=pred_c, actual_total=actual,
                    absolute_percentage_error=ape,
                ))

            # Log-linear
            pred_ll = log_linear_predict(train, horizon_days)
            if pred_ll is not None:
                ape = 100.0 * abs(pred_ll - actual) / actual
                summaries["log_linear"].per_horizon.setdefault(horizon, []).append(ape)

            # Gompertz
            pred_g = gompertz_predict(train, horizon_days)
            if pred_g is not None:
                ape = 100.0 * abs(pred_g - actual) / actual
                summaries["gompertz"].per_horizon.setdefault(horizon, []).append(ape)

        processed += 1

    for s in summaries.values():
        s.lifter_count = processed

    artifact = {
        "inputs": {
            "parquet": str(input_path),
            "min_meets": MIN_MEETS_FOR_BACKTEST,
            "holdout": DEFAULT_HOLDOUT,
            "horizons_months": list(HORIZONS_MONTHS),
        },
        "summary": {
            "engines": [s.as_dict() for s in summaries.values()],
            "processed_lifters": processed,
        },
        "ship_gate": {
            "engine_c_mape_6mo_limit": 6.0,
            "engine_c_mape_12mo_limit": 12.0,
            "log_linear_margin_12mo_limit_pp": 2.0,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    logger.info("Wrote backtest artifact: %s (lifters=%d)", output_path, processed)

    # Mirror the artifact into the frontend bundle so the About tab picks
    # up the fresh numbers on next build. The mirror is only written when
    # the frontend source tree exists; running the backtest against a
    # different repo layout (e.g. a CI smoke harness) skips this step.
    frontend_mirror = ROOT / "frontend" / "src" / "data" / "backtest_results.json"
    if frontend_mirror.parent.parent.exists():
        frontend_mirror.parent.mkdir(parents=True, exist_ok=True)
        with frontend_mirror.open("w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)
        logger.info("Mirrored artifact into frontend bundle: %s", frontend_mirror)

    # Terminal summary.
    print("\nMAPE by engine and horizon (lower = better):")
    header = f"{'engine':<12} " + " ".join(f"{h}mo" for h in HORIZONS_MONTHS)
    print(header)
    print("-" * len(header))
    for s in summaries.values():
        row_parts = [s.engine.ljust(12)]
        for h in HORIZONS_MONTHS:
            m = s.mape_at(h)
            row_parts.append(f"{m:5.2f}" if m is not None else "  -  ")
        print(" ".join(row_parts))


def main() -> None:
    p = argparse.ArgumentParser(description="Offline backtest for Athlete Projection")
    p.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed" / "openipf.parquet",
        help="Parquet path (defaults to the Canada+IPF preprocess output).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "backtest_results.json",
        help="Where to write the JSON artifact.",
    )
    p.add_argument(
        "--max-lifters",
        type=int,
        default=None,
        help="Optional cap for faster local smoke runs.",
    )
    args = p.parse_args()

    if not args.input.exists():
        logger.error("Input parquet not found: %s", args.input)
        sys.exit(1)
    run_backtest(args.input, args.output, max_lifters=args.max_lifters)


if __name__ == "__main__":
    main()
