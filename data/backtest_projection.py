"""Offline backtest for Athlete Projection Engine C vs alternatives.

Walk-forward evaluation. For each eligible lifter:

  1. Split their career at ``last_meet_date - HOLDOUT_SPAN_MONTHS``. Meets at
     or before the cut are training; everything after is held out.
  2. Fit Engine C on the training meets and project forward to the EXACT
     date of each held-out meet.
  3. Bucket each held-out meet by how far it sits from the last training
     meet (3 / 6 / 12 / 18 / 24 / 36 months) and record the absolute
     percentage error there, alongside log-linear and Gompertz baselines.

Three properties of this harness are load-bearing, and all three were wrong
in the version that produced the numbers shipped before 2026-08-09:

  * **It runs the engine that ships.** Engine C projects squat, bench and
    deadlift independently -- each with its own level, Huber slope,
    shrinkage weight and cohort cell -- and sums the three. The previous
    harness fit the TOTAL series against the SQUAT cohort cell as a
    "total-level proxy", which understates the cohort slope roughly
    threefold and uses a level that no production code path computes. Both
    now come from `project_from_history`, the same function the API calls.
  * **Cohort cells are fit on training rows only.** They were previously
    fit on the full frame, so every lifter's held-out meets fed the cohort
    slopes that were then used to predict those same meets.
  * **Predictions are scored at the held-out meet's real date.** The
    previous harness predicted at a nominal horizon and accepted any meet
    within +/- 90 days as the actual. At the 3-month horizon that tolerance
    is the entire horizon, at 36 months it is 8 percent of it, so it
    injected an error that shrank with horizon -- directly corrupting the
    one question the backtest exists to answer, which is whether the margin
    between engines WIDENS with horizon.

Engine comparisons are PAIRED. Gompertz only returns a prediction when
`curve_fit` converges, so its raw MAPE is computed on an easier subset than
Engine C's. Every head-to-head number here is computed on the observations
where both engines produced a prediction, with a bootstrap interval
clustered on lifter (one lifter contributes several correlated
observations, so an observation-level bootstrap would overstate precision).

Usage:
    python data/backtest_projection.py \
        --input data/processed/openipf_global.parquet \
        --output data/backtest_results.json

Not wired into CI. Not imported by any production module. The About page
consumes the JSON artifact as a static file.
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

# Add the backend package to the Python path so we can reuse Engine C itself.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import athlete_projection as ap  # noqa: E402
from backend.app.athlete_projection_tables import (  # noqa: E402
    LIFT_COLS,
    GlpCohortCell,
)

logger = logging.getLogger("backtest")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

ARTIFACT_SCHEMA_VERSION = 2

HORIZONS_MONTHS: tuple[int, ...] = (3, 6, 12, 18, 24, 36)

# Half-open [low, high) elapsed-month windows that map a held-out meet to a
# horizon bucket. Contiguous and non-overlapping, so a meet lands in at most
# one bucket. Below 1.5 months is same-training-block noise; past 42 months
# there is no bucket to answer for.
HORIZON_BUCKETS: tuple[tuple[int, float, float], ...] = (
    (3, 1.5, 4.5),
    (6, 4.5, 9.0),
    (12, 9.0, 15.0),
    (18, 15.0, 21.0),
    (24, 21.0, 30.0),
    (36, 30.0, 42.0),
)

# Hold out the final N months of every career so the longest horizon is
# reachable for every lifter in the sample, rather than only for the ones
# who happened to compete often.
HOLDOUT_SPAN_MONTHS = 36

# Career meets required to enter the pool at all (unchanged from v1, so the
# population stays the long-career pool the shipped numbers described).
MIN_MEETS_FOR_BACKTEST = 15

# Training meets required after the split. Matches production's
# SMALL_N_THRESHOLD so the measured regime is the one where production does
# NOT clamp the horizon down to 6 months.
MIN_TRAIN_MEETS = 5

ENGINE_KEYS = ("engine_c", "log_linear", "gompertz", "flat_last", "flat_level")

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260809

# Ship gates, superseded 2026-08-09 by docs/adr/0004.
#
# The previous set was three MAPE thresholds, and all three passed on an
# engine running 5 to 6 percent HIGH at both horizons the app serves. Every
# one of them measured the magnitude of the error and none measured its
# direction, so a systematically biased engine was invisible to them. Bias
# gates now lead, with a floor on the short-history group so that a fix
# which damps the slope to nothing cannot pass by starting to under-predict
# newer lifters instead.
SHIP_GATES: dict[str, float] = {
    "engine_c_bias_12mo_limit_pp": 2.0,
    "engine_c_bias_18mo_limit_pp": 2.0,
    "engine_c_mape_6mo_limit": 6.0,
    "engine_c_mape_12mo_limit": 12.0,
    "challenger_margin_12mo_limit_pp": 2.0,
}


@dataclass
class Observation:
    """One (lifter, horizon bucket) scoring point."""

    name: str
    horizon: int
    elapsed_months: float
    actual_total: float
    predictions: dict[str, float] = field(default_factory=dict)

    def ape(self, engine: str) -> float | None:
        pred = self.predictions.get(engine)
        if pred is None or self.actual_total <= 0:
            return None
        return 100.0 * abs(pred - self.actual_total) / self.actual_total

    def spe(self, engine: str) -> float | None:
        """Signed percentage error. Positive means the engine projected HIGH.

        Reported alongside MAPE because the two answer different questions.
        Engine C's level is the sum of each lift's max-of-last-3, an upper
        envelope that no single meet need ever have hit, and its slope does
        not decay. Both push predictions high, and only the signed error
        distinguishes "the engine is noisy" from "the engine overshoots" --
        which is the difference between swapping the engine and fixing the
        level convention.
        """
        pred = self.predictions.get(engine)
        if pred is None or self.actual_total <= 0:
            return None
        return 100.0 * (pred - self.actual_total) / self.actual_total


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
            SELECT Name, Sex, Age, BodyweightKg, Date, Event, Division,
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
        ORDER BY s.Name, s.Date, s.TotalKg,
                 s.Best3SquatKg, s.Best3BenchKg, s.Best3DeadliftKg
    """
    return conn.execute(sql).df()


def split_train_holdout(
    lifter_meets: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Split one lifter's career at last_meet - HOLDOUT_SPAN_MONTHS.

    Returns None when the split leaves too few training meets or nothing
    held out.
    """
    dates = pd.to_datetime(lifter_meets["Date"])
    cut = dates.max() - pd.DateOffset(months=HOLDOUT_SPAN_MONTHS)
    train = lifter_meets[dates <= cut]
    holdout = lifter_meets[dates > cut]
    if len(train) < MIN_TRAIN_MEETS or holdout.empty:
        return None
    return train.reset_index(drop=True), holdout.reset_index(drop=True)


def iter_lifters(df: pd.DataFrame, max_lifters: int | None = None):
    """Yield (name, per-lifter frame sorted by date).

    Uses groupby rather than a boolean mask per name: the pool is tens of
    thousands of lifters over hundreds of thousands of rows, and masking
    inside the loop makes the pass quadratic.
    """
    count = 0
    for name, group in df.sort_values(["Name", "Date"]).groupby("Name", sort=False):
        if max_lifters is not None and count >= max_lifters:
            return
        count += 1
        yield str(name), group.reset_index(drop=True)


def bucket_for(elapsed_months: float) -> int | None:
    for horizon, low, high in HORIZON_BUCKETS:
        if low <= elapsed_months < high:
            return horizon
    return None


def select_scoring_meets(
    train: pd.DataFrame, holdout: pd.DataFrame,
) -> list[tuple[int, float, float]]:
    """Pick at most one held-out meet per horizon bucket.

    Returns (horizon, elapsed_months, actual_total) triples. Where several
    held-out meets share a bucket, the one closest to the bucket's nominal
    horizon wins, so a lifter contributes a single observation per bucket
    and the cluster bootstrap sees a clean lifter -> observations mapping.
    """
    anchor = pd.to_datetime(train["Date"]).max()
    best: dict[int, tuple[float, float, float]] = {}
    for _, row in holdout.iterrows():
        elapsed_days = (pd.to_datetime(row["Date"]) - anchor).days
        elapsed_months = elapsed_days / ap.DAYS_PER_MONTH
        horizon = bucket_for(elapsed_months)
        if horizon is None:
            continue
        total = row["TotalKg"]
        if total is None or pd.isna(total) or float(total) <= 0:
            continue
        distance = abs(elapsed_months - horizon)
        prior = best.get(horizon)
        if prior is None or distance < prior[0]:
            best[horizon] = (distance, elapsed_months, float(total))
    return [
        (horizon, elapsed, total)
        for horizon, (_d, elapsed, total) in sorted(best.items())
    ]


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


def engine_c_predict(
    train: pd.DataFrame,
    name: str,
    elapsed_months: float,
    cohort_lookup,
) -> float | None:
    """Project a total via the production Engine C code path.

    `clamp_horizon=False` because production caps the horizon at 18 months
    in the UI. The 24 and 36 month readings are diagnostic for the cascade
    decision, not a claim about a shipped capability.

    `km_lookup` returns None, giving a Kaplan-Meier multiplier of 1.0. That
    is not an approximation: the K-M multiplier enters only the prediction
    interval, never the projected level, and this harness scores point
    predictions.
    """
    result = ap.project_from_history(
        lifter_df=train,
        lifter_name=name,
        horizon_months=elapsed_months,
        n_points=6,
        cohort_lookup=cohort_lookup,
        km_lookup=lambda _division: None,
        clamp_horizon=False,
    )
    if result is None or not result.total_projected_points:
        return None
    return float(result.total_projected_points[-1]["projected_kg"])


def log_linear_predict(train: pd.DataFrame, elapsed_months: float) -> float | None:
    """Fit log(total) ~ time via OLS and project forward."""
    totals = train["TotalKg"].astype(float).to_numpy()
    if len(totals) < 3 or np.any(totals <= 0):
        return None
    dates = pd.to_datetime(train["Date"].values)
    days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
    if len(np.unique(days)) < 2:
        return None
    slope, intercept = np.polyfit(days, np.log(totals), 1)
    future_day = float(days[-1]) + elapsed_months * ap.DAYS_PER_MONTH
    return float(np.exp(slope * future_day + intercept))


def flat_last_predict(train: pd.DataFrame, _elapsed_months: float) -> float | None:
    """Naive persistence: predict the last training total, unchanged.

    The control that keeps the cascade decision honest. Gompertz saturates
    and Engine C does not, so on a plateaued career Gompertz wins simply by
    predicting less growth. If naive persistence ALSO beats Engine C at the
    long horizons, the finding is "Engine C extrapolates growth too far",
    and the cheap fix is slope damping, not a second engine. If Gompertz
    beats persistence as well, it is genuinely modelling the plateau shape
    rather than just refusing to extrapolate.
    """
    totals = train["TotalKg"].astype(float).to_numpy()
    if len(totals) == 0:
        return None
    last = float(totals[-1])
    return last if last > 0 else None


def flat_level_predict(train: pd.DataFrame, _elapsed_months: float) -> float | None:
    """Engine C's starting level, held flat. Isolates the level convention.

    Engine C's level is the sum of each lift's max-of-last-3, an upper
    envelope that no single meet need ever have hit: a lifter's best squat,
    best bench and best deadlift can come from three different days. This
    engine keeps that level and removes the slope, so the pair
    (flat_last, flat_level) splits Engine C's overshoot into the part
    coming from the level convention and the part coming from projecting
    growth forward. That distinction decides whether the fix is a one-line
    slope change or a different level definition.
    """
    total = 0.0
    for col in LIFT_COLS.values():
        if col not in train.columns:
            return None
        values = [float(v) for v in train[col].tolist() if v is not None and not pd.isna(v)]
        level = ap.compute_current_level(values)
        if level is None:
            return None
        total += level
    return total if total > 0 else None


def gompertz_predict(train: pd.DataFrame, elapsed_months: float) -> float | None:
    """Fit y = A * exp(-B * exp(-C * t)) via non-linear least squares."""
    totals = train["TotalKg"].astype(float).to_numpy()
    if len(totals) < 4 or np.any(totals <= 0):
        return None
    dates = pd.to_datetime(train["Date"].values)
    days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
    if len(np.unique(days)) < 2:
        return None
    try:
        from scipy.optimize import curve_fit

        def gompertz(t: np.ndarray, a: float, b: float, c: float) -> np.ndarray:
            return a * np.exp(-b * np.exp(-c * t))

        popt, _ = curve_fit(
            gompertz, days, totals,
            p0=[float(np.max(totals) * 1.1), 1.0, 0.001], maxfev=2000,
        )
        future_day = float(days[-1]) + elapsed_months * ap.DAYS_PER_MONTH
        return float(gompertz(np.array([future_day]), *popt)[0])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cohort cells (training rows only)
# ---------------------------------------------------------------------------


def fit_cohort_cells_from_frame(hist: pd.DataFrame) -> dict:
    """Fit the production cohort matrix on an in-memory frame.

    The production fitter filters on Country + ParentFederation, so the
    frame is stamped Canada/IPF to pass that filter. On a global run that
    stamp is a fiction and deliberately so: the point is to run the
    production fitter over a larger pool, not to model Canada.
    """
    frame = hist[[
        "Name", "Sex", "Age", "BodyweightKg", "Date", "Equipment",
        "Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg", "TotalKg",
    ]].copy()
    frame["Event"] = "SBD"
    frame["Country"] = "Canada"
    frame["ParentFederation"] = "IPF"

    # Determinism. The production fitter assigns each lifter a GLP bracket
    # from `groupby("Name").tail(1)` over a frame ordered by (Name, Date),
    # and 1,664 lifter-days in this pool carry more than one SBD row. With
    # ties in the sort key and multi-threaded execution, which row lands
    # last is not stable across runs, so a handful of lifters change
    # bracket and the reported MAPE moves by up to ~0.15 pp. That is far
    # below the effects this harness measures, but a decision artifact
    # that cannot be reproduced exactly is not worth defending. Sort on a
    # full key and pin execution to one thread with insertion order kept.
    frame = frame.sort_values(
        ["Name", "Date", "TotalKg", "Best3SquatKg", "Best3BenchKg", "Best3DeadliftKg"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    conn = duckdb.connect(database=":memory:")
    conn.execute("SET threads TO 1")
    conn.execute("SET preserve_insertion_order = true")
    conn.register("openipf", frame)
    return ap._fit_cohort_cells(conn)


def make_cohort_lookup(cells: dict):
    def lookup(division: str, bracket: str, lift: str) -> GlpCohortCell | None:
        return cells.get((division, bracket, lift))

    return lookup


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def summarize_engine(observations: list[Observation], engine: str) -> dict[str, Any]:
    """Per-engine MAPE on that engine's OWN sample.

    Reported for transparency only. These numbers are NOT comparable across
    engines, because each engine answers on the subset where it produced a
    prediction. Cross-engine claims come from `head_to_head`.
    """
    per_horizon: dict[str, dict[str, Any]] = {}
    for horizon in HORIZONS_MONTHS:
        in_bucket = [o for o in observations if o.horizon == horizon]
        vals = [a for a in (o.ape(engine) for o in in_bucket) if a is not None]
        signed = [s for s in (o.spe(engine) for o in in_bucket) if s is not None]
        per_horizon[str(horizon)] = {
            "mape": float(np.mean(vals)) if vals else None,
            "median_ape": float(np.median(vals)) if vals else None,
            "bias": float(np.mean(signed)) if signed else None,
            "n": len(vals),
            # Share of scoreable observations this engine answered at all.
            # Gompertz declines whenever curve_fit fails to converge, and
            # that coverage IS the cascade's fallback rate.
            "coverage": (len(vals) / len(in_bucket)) if in_bucket else None,
        }
    return {"engine": engine, "by_horizon": per_horizon}


def _cluster_bootstrap_ci(
    diffs_by_lifter: dict[str, list[float]],
    resamples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    """95% CI for the mean paired difference, resampling LIFTERS not rows.

    One lifter contributes several correlated observations; resampling rows
    independently would treat those as independent evidence and report an
    interval that is too narrow.
    """
    names = list(diffs_by_lifter)
    if len(names) < 2:
        return None, None
    rng = np.random.default_rng(seed)
    per_lifter = [np.asarray(diffs_by_lifter[n], dtype=float) for n in names]
    means = np.empty(resamples, dtype=float)
    idx_space = len(names)
    for i in range(resamples):
        picks = rng.integers(0, idx_space, size=idx_space)
        pooled = np.concatenate([per_lifter[p] for p in picks])
        means[i] = pooled.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def head_to_head(
    observations: list[Observation],
    challenger: str,
    baseline: str = "engine_c",
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Paired comparison of `challenger` against `baseline`.

    Only observations where BOTH engines produced a prediction count. The
    sign convention is (challenger - baseline), so a negative mean
    difference means the challenger is more accurate.
    """
    per_horizon: dict[str, Any] = {}
    for horizon in HORIZONS_MONTHS:
        diffs_by_lifter: dict[str, list[float]] = {}
        base_apes: list[float] = []
        chal_apes: list[float] = []
        wins = 0
        for obs in observations:
            if obs.horizon != horizon:
                continue
            a_base = obs.ape(baseline)
            a_chal = obs.ape(challenger)
            if a_base is None or a_chal is None:
                continue
            base_apes.append(a_base)
            chal_apes.append(a_chal)
            diffs_by_lifter.setdefault(obs.name, []).append(a_chal - a_base)
            if a_chal < a_base:
                wins += 1
        n = len(base_apes)
        if n == 0:
            per_horizon[str(horizon)] = {
                "n_paired": 0, "mape_baseline": None, "mape_challenger": None,
                "mean_diff": None, "ci_low": None, "ci_high": None,
                "challenger_win_rate": None, "n_lifters": 0,
            }
            continue
        all_diffs = [d for ds in diffs_by_lifter.values() for d in ds]
        ci_low, ci_high = _cluster_bootstrap_ci(diffs_by_lifter, resamples, seed)
        per_horizon[str(horizon)] = {
            "n_paired": n,
            "n_lifters": len(diffs_by_lifter),
            "mape_baseline": float(np.mean(base_apes)),
            "mape_challenger": float(np.mean(chal_apes)),
            "mean_diff": float(np.mean(all_diffs)),
            "ci_low": ci_low,
            "ci_high": ci_high,
            "challenger_win_rate": wins / n,
        }
    return {"challenger": challenger, "baseline": baseline, "by_horizon": per_horizon}


# ---------------------------------------------------------------------------
# Backtest driver
# ---------------------------------------------------------------------------


def collect_observations(
    df: pd.DataFrame,
    cohort_lookup,
    max_lifters: int | None = None,
) -> tuple[list[Observation], dict[str, int]]:
    observations: list[Observation] = []
    counters = {"eligible": 0, "split_rejected": 0, "no_bucket": 0, "scored": 0}

    groups = iter_lifters(df, max_lifters)

    for name, lifter_meets in groups:
        counters["eligible"] += 1
        split = split_train_holdout(lifter_meets)
        if split is None:
            counters["split_rejected"] += 1
            continue
        train, holdout = split

        scoring = select_scoring_meets(train, holdout)
        if not scoring:
            counters["no_bucket"] += 1
            continue

        for horizon, elapsed_months, actual in scoring:
            obs = Observation(
                name=name, horizon=horizon,
                elapsed_months=elapsed_months, actual_total=actual,
            )
            pred_c = engine_c_predict(train, name, elapsed_months, cohort_lookup)
            if pred_c is not None:
                obs.predictions["engine_c"] = pred_c
            pred_ll = log_linear_predict(train, elapsed_months)
            if pred_ll is not None:
                obs.predictions["log_linear"] = pred_ll
            pred_g = gompertz_predict(train, elapsed_months)
            if pred_g is not None:
                obs.predictions["gompertz"] = pred_g
            pred_flat = flat_last_predict(train, elapsed_months)
            if pred_flat is not None:
                obs.predictions["flat_last"] = pred_flat
            pred_flat_level = flat_level_predict(train, elapsed_months)
            if pred_flat_level is not None:
                obs.predictions["flat_level"] = pred_flat_level
            if obs.predictions:
                observations.append(obs)
                counters["scored"] += 1

    return observations, counters


def load_observations(path: Path) -> list[Observation]:
    """Rehydrate observations from a previous run's dump."""
    out: list[Observation] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out.append(Observation(
                name=row["name"],
                horizon=int(row["horizon"]),
                elapsed_months=float(row["elapsed_months"]),
                actual_total=float(row["actual_total"]),
                predictions={k: float(v) for k, v in row["predictions"].items()},
            ))
    return out


def build_artifact(
    observations: list[Observation],
    input_path: Path,
    pool_lifters: int,
) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "inputs": {
            "parquet": str(input_path),
            "min_career_meets": MIN_MEETS_FOR_BACKTEST,
            "min_train_meets": MIN_TRAIN_MEETS,
            "holdout_span_months": HOLDOUT_SPAN_MONTHS,
            "horizons_months": list(HORIZONS_MONTHS),
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        },
        "summary": {
            "engines": [summarize_engine(observations, e) for e in ENGINE_KEYS],
            "scored_lifters": len({o.name for o in observations}),
            "observations": len(observations),
            "pool_lifters": pool_lifters,
        },
        "head_to_head": [
            head_to_head(observations, "gompertz"),
            head_to_head(observations, "flat_last"),
            head_to_head(observations, "flat_level"),
            head_to_head(observations, "log_linear"),
            # The decisive one for the cascade: does Gompertz earn its
            # complexity over simply not extrapolating? Both challengers
            # beat Engine C at long horizons, so beating Engine C is not
            # evidence for Gompertz specifically.
            head_to_head(observations, "gompertz", baseline="flat_last"),
        ],
        "ship_gate": SHIP_GATES,
    }


def rebuild_from_observations(
    observations_path: Path,
    output_path: Path,
    input_path: Path,
    pool_lifters: int,
) -> None:
    """Recompute the artifact from a dump, without re-scoring.

    The scoring pass is ~40 minutes. Adding a comparison, correcting a
    gate threshold, or fixing a summary statistic should not cost that,
    and if it does, the temptation is to hand-edit the committed artifact
    instead. That is how a generated file starts disagreeing with the code
    that generates it.
    """
    observations = load_observations(observations_path)
    logger.info("Rehydrated %d observations from %s", len(observations), observations_path)
    artifact = build_artifact(observations, input_path, pool_lifters)
    write_artifact(artifact, output_path)
    print_summary(artifact)


def write_artifact(artifact: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    logger.info("Wrote backtest artifact: %s", output_path)

    frontend_mirror = ROOT / "frontend" / "src" / "data" / "backtest_results.json"
    if frontend_mirror.parent.parent.exists():
        frontend_mirror.parent.mkdir(parents=True, exist_ok=True)
        with frontend_mirror.open("w", encoding="utf-8") as f:
            json.dump(artifact, f, indent=2)
        logger.info("Mirrored artifact into frontend bundle: %s", frontend_mirror)


def run_backtest(
    input_path: Path,
    output_path: Path,
    max_lifters: int | None = None,
) -> None:
    logger.info("Loading parquet: %s", input_path)
    conn = load_parquet_into_duckdb(input_path)

    logger.info("Selecting lifters with >= %d SBD meets", MIN_MEETS_FOR_BACKTEST)
    df = select_backtest_lifters(conn)
    if df.empty:
        logger.warning("No backtest-eligible lifters in dataset. Exiting.")
        return
    logger.info("Pool: %d lifters, %d meets", df["Name"].nunique(), len(df))

    # Cohort cells fit on TRAINING rows only. Fitting on the full frame
    # leaks every lifter's held-out meets into the slopes used to predict
    # those same meets.
    logger.info("Building training-only frame for cohort fitting")
    train_parts: list[pd.DataFrame] = []
    for _name, lifter_meets in iter_lifters(df):
        split = split_train_holdout(lifter_meets)
        if split is not None:
            train_parts.append(split[0])
    if not train_parts:
        logger.warning("No lifter survived the train/holdout split. Exiting.")
        return
    train_frame = pd.concat(train_parts, ignore_index=True)
    logger.info(
        "Training frame: %d lifters, %d meets", train_frame["Name"].nunique(),
        len(train_frame),
    )

    cells = fit_cohort_cells_from_frame(train_frame)
    logger.info("Cohort cells fit on training rows: %d", len(cells))
    cohort_lookup = make_cohort_lookup(cells)

    logger.info("Scoring lifters")
    observations, counters = collect_observations(df, cohort_lookup, max_lifters)
    logger.info(
        "Observations: %d from %d lifters (%d rejected at split, %d with no "
        "held-out meet in any horizon bucket)",
        len(observations),
        len({o.name for o in observations}),
        counters["split_rejected"],
        counters["no_bucket"],
    )

    artifact = build_artifact(observations, input_path, int(df["Name"].nunique()))

    # Dump the raw observations next to the artifact, so that adding a
    # comparison or correcting a threshold can be replayed with
    # --from-observations instead of re-scoring. Gitignored: it is an
    # analysis input, not a product artifact.
    obs_path = output_path.with_name(output_path.stem + "_observations.jsonl")
    with obs_path.open("w", encoding="utf-8") as f:
        for obs in observations:
            f.write(json.dumps({
                "name": obs.name,
                "horizon": obs.horizon,
                "elapsed_months": round(obs.elapsed_months, 3),
                "actual_total": obs.actual_total,
                "predictions": {k: round(v, 2) for k, v in obs.predictions.items()},
            }) + "\n")
    logger.info("Wrote raw observations: %s (%d rows)", obs_path, len(observations))

    write_artifact(artifact, output_path)
    print_summary(artifact)


def print_summary(artifact: dict[str, Any]) -> None:
    horizons = artifact["inputs"]["horizons_months"]
    print("\nMAPE by engine and horizon, each on its OWN sample (not comparable):")
    header = f"{'engine':<12} " + " ".join(f"{h:>12}mo" for h in horizons)
    print(header)
    print("-" * len(header))
    for summary in artifact["summary"]["engines"]:
        parts = [summary["engine"].ljust(12)]
        for h in horizons:
            cell = summary["by_horizon"][str(h)]
            parts.append(
                f"{cell['mape']:8.2f} (n={cell['n']:>4})"
                if cell["mape"] is not None else f"{'-':>14}"
            )
        print(" ".join(parts))

    print("\nSigned bias, percent (positive = projected HIGH):")
    print(header)
    print("-" * len(header))
    for summary in artifact["summary"]["engines"]:
        parts = [summary["engine"].ljust(12)]
        for h in horizons:
            cell = summary["by_horizon"][str(h)]
            parts.append(
                f"{cell['bias']:+8.2f} (c={cell['coverage']:.0%})"
                if cell["bias"] is not None else f"{'-':>14}"
            )
        print(" ".join(parts))

    for h2h in artifact["head_to_head"]:
        print(
            f"\nPAIRED {h2h['challenger']} vs {h2h['baseline']} "
            "(negative mean diff = challenger better):"
        )
        print(f"{'horizon':>8} {'n':>6} {'base':>8} {'chal':>8} {'diff':>8} {'95% CI':>18} {'win rate':>9}")  # noqa: E501
        for h in horizons:
            c = h2h["by_horizon"][str(h)]
            if not c["n_paired"]:
                print(f"{h:>6}mo {0:>6}")
                continue
            ci = (
                f"[{c['ci_low']:+.2f}, {c['ci_high']:+.2f}]"
                if c["ci_low"] is not None else "n/a"
            )
            print(
                f"{h:>6}mo {c['n_paired']:>6} {c['mape_baseline']:>8.2f} "
                f"{c['mape_challenger']:>8.2f} {c['mean_diff']:>+8.2f} {ci:>18} "
                f"{c['challenger_win_rate']:>8.1%}"
            )


def main() -> None:
    p = argparse.ArgumentParser(description="Offline backtest for Athlete Projection")
    p.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed" / "openipf_global.parquet",
        help="Parquet path (defaults to the global preprocess output).",
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
    p.add_argument(
        "--from-observations",
        type=Path,
        default=None,
        help=(
            "Rebuild the artifact from a previous run's observations dump "
            "instead of re-scoring (~40 min saved). Use after changing a "
            "summary statistic, a gate threshold, or adding a comparison."
        ),
    )
    p.add_argument(
        "--pool-lifters",
        type=int,
        default=0,
        help="Pool size to record when rebuilding with --from-observations.",
    )
    args = p.parse_args()

    if args.from_observations is not None:
        if not args.from_observations.exists():
            logger.error("Observations dump not found: %s", args.from_observations)
            sys.exit(1)
        rebuild_from_observations(
            args.from_observations, args.output, args.input, args.pool_lifters,
        )
        return

    if not args.input.exists():
        logger.error("Input parquet not found: %s", args.input)
        sys.exit(1)
    run_backtest(args.input, args.output, max_lifters=args.max_lifters)


if __name__ == "__main__":
    main()
