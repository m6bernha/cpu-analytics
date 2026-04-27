"""Engine D MixedLM convergence probe (Path A).

Fits ``statsmodels.MixedLM`` per (age_division x ipf_gl_bracket x lift) cohort
cell on a sample of Canada+IPF lifters and reports convergence rate. The probe
exists to answer one go/no-go question before we wire MixedLM into
``backend.app.athlete_projection.mixed_effects_projection``:

    Does MixedLM converge cleanly enough to be a defensible production engine?

Two passes are run by default:

* ``p1_min15_meets``  -- N=200 lifters with >= 15 SBD meets (optimistic).
* ``p2_min5_meets``   -- N=200 lifters with >=  5 SBD meets (realistic floor).

The artifact lives at ``data/processed/mixedlm_convergence_probe.json`` and is
intentionally gitignored. The harness exits 0 regardless of the verdict; the
JSON encodes the decision-gate outcome for downstream review.

Usage::

    ./.venv/Scripts/python.exe -m data.probe_mixedlm_convergence
    ./.venv/Scripts/python.exe -m data.probe_mixedlm_convergence --pass 1
    ./.venv/Scripts/python.exe -m data.probe_mixedlm_convergence --max-lifters 50

Not wired into CI. Not imported by any production module.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

# Add the backend package to sys.path so we can reuse Engine C helpers.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import athlete_projection as ap  # noqa: E402
from backend.app.ipf_gl_points import (  # noqa: E402
    GLP_BRACKET_LABELS,
    assign_glp_bracket,
    ipf_gl_points,
)
from backend.app.progression import age_to_category  # noqa: E402

logger = logging.getLogger("probe_mixedlm")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# =============================================================================
# Constants -- mirror Engine C defaults from athlete_projection.py
# =============================================================================

LIFT_COLS: dict[str, str] = {
    "squat":    "Best3SquatKg",
    "bench":    "Best3BenchKg",
    "deadlift": "Best3DeadliftKg",
}

LIFT_KEYS: tuple[str, ...] = ("squat", "bench", "deadlift")

# Re-use Engine C cell-floor so the probe mirrors what would actually ship.
MIN_LIFTERS_PER_CELL: int = ap.MIN_COHORT_CELL_SIZE  # 20
MIN_MEETS_PER_CELL: int = 60                          # ~3 meets average per lifter
SAMPLE_SIZE: int = 200
MAXITER: int = 200
SLOW_FIT_THRESHOLD_S: float = 30.0
SEED: int = 42

DAYS_PER_YEAR: float = 365.25  # rescaling for numerical conditioning


# =============================================================================
# DTOs
# =============================================================================


@dataclass(frozen=True)
class CellFitOutcome:
    cell_key: tuple[str, str, str]   # (age_division, anchor_bracket, lift)
    n_lifters: int
    n_meets: int
    runtime_s: float
    converged: bool
    failure_mode: str | None         # None when converged
    merged_from: tuple[str, ...]     # bracket labels combined; (anchor,) if no merge
    is_global_fallback: bool         # True if division-global merge was applied

    def as_dict(self) -> dict[str, Any]:
        return {
            "cell_key": list(self.cell_key),
            "n_lifters": self.n_lifters,
            "n_meets": self.n_meets,
            "runtime_s": round(self.runtime_s, 3),
            "converged": self.converged,
            "failure_mode": self.failure_mode,
            "merged_from": list(self.merged_from),
            "is_global_fallback": self.is_global_fallback,
        }


@dataclass
class PassResult:
    name: str
    min_meets: int
    n_lifters_sampled: int
    merge_strategy: str = "none"
    cell_outcomes: list[CellFitOutcome] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        per_lift: dict[str, Any] = {}
        for lift in LIFT_KEYS:
            outcomes = [o for o in self.cell_outcomes if o.cell_key[2] == lift]
            n_attempted = len(outcomes)
            n_converged = sum(1 for o in outcomes if o.converged)
            runtimes = [o.runtime_s for o in outcomes]
            failure_breakdown: dict[str, int] = {}
            for o in outcomes:
                if not o.converged and o.failure_mode is not None:
                    failure_breakdown[o.failure_mode] = (
                        failure_breakdown.get(o.failure_mode, 0) + 1
                    )
            per_lift[lift] = {
                "n_cells_attempted": n_attempted,
                "n_cells_converged": n_converged,
                "convergence_rate": (
                    round(n_converged / n_attempted, 3) if n_attempted else None
                ),
                "p50_runtime_s": (
                    round(float(np.median(runtimes)), 3) if runtimes else None
                ),
                "p95_runtime_s": (
                    round(float(np.percentile(runtimes, 95)), 3)
                    if runtimes else None
                ),
                "failure_breakdown": failure_breakdown,
            }
        all_attempted = len(self.cell_outcomes)
        all_converged = sum(1 for o in self.cell_outcomes if o.converged)
        overall = (
            round(all_converged / all_attempted, 3) if all_attempted else None
        )
        n_global_fallback = sum(
            1 for o in self.cell_outcomes if o.is_global_fallback
        )
        n_merged = sum(
            1 for o in self.cell_outcomes if len(o.merged_from) > 1
        )
        return {
            "name": self.name,
            "min_meets": self.min_meets,
            "merge_strategy": self.merge_strategy,
            "n_lifters_sampled": self.n_lifters_sampled,
            "fits": per_lift,
            "overall_convergence_rate": overall,
            "n_cells_attempted_total": all_attempted,
            "n_cells_converged_total": all_converged,
            "n_cells_merged": n_merged,
            "n_cells_global_fallback": n_global_fallback,
        }


# =============================================================================
# Data loading
# =============================================================================


def load_parquet_into_duckdb(parquet_path: Path) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(database=":memory:")
    conn.execute(
        "CREATE VIEW openipf AS "
        f"SELECT * FROM parquet_scan('{parquet_path.as_posix()}')"
    )
    return conn


def select_lifters_with_floor(
    conn: duckdb.DuckDBPyConnection, min_meets: int
) -> pd.DataFrame:
    """Return all SBD meets for raw lifters with >= min_meets meets and full
    BW/Age/Sex columns. Sorted by (Name, Date)."""
    sql = f"""
        WITH sbd AS (
            SELECT Name, Sex, Age, BodyweightKg, Date,
                   Best3SquatKg, Best3BenchKg, Best3DeadliftKg, TotalKg,
                   Equipment
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
            HAVING COUNT(*) >= {int(min_meets)}
        )
        SELECT s.*
        FROM sbd s
        JOIN counts c USING (Name)
        ORDER BY s.Name, s.Date
    """
    return conn.execute(sql).df()


def sample_lifters(
    df: pd.DataFrame, n: int, seed: int = SEED
) -> list[str]:
    """Deterministically pick at most n lifter names from df."""
    rng = np.random.default_rng(seed)
    unique_names = df["Name"].unique()
    if len(unique_names) <= n:
        return list(unique_names)
    return list(rng.choice(unique_names, size=n, replace=False))


# =============================================================================
# Cell partitioning
# =============================================================================


def assign_lifter_cell(
    last_meet: pd.Series,
) -> tuple[str, str] | None:
    """Compute (age_division, glp_bracket) for a lifter's most recent meet.

    Returns None when the meet falls outside the supported age divisions or
    GL points cannot be computed.
    """
    division = age_to_category(float(last_meet["Age"]))
    if division not in ap.AGE_DIVISIONS:
        return None
    glp = ipf_gl_points(
        total_kg=float(last_meet["TotalKg"]),
        bw_kg=float(last_meet["BodyweightKg"]),
        age=float(last_meet["Age"]),
        sex=str(last_meet["Sex"]),
    )
    bracket = assign_glp_bracket(glp)
    return (division, bracket)


def build_cell_partition(
    df: pd.DataFrame, lifter_names: list[str]
) -> dict[tuple[str, str], list[str]]:
    """Map each (division, bracket) cell to the list of lifter names whose
    most-recent meet falls in that cell."""
    partition: dict[tuple[str, str], list[str]] = {}
    for name in lifter_names:
        meets = df[df["Name"] == name]
        if meets.empty:
            continue
        last_meet = meets.iloc[-1]
        cell = assign_lifter_cell(last_meet)
        if cell is None:
            continue
        partition.setdefault(cell, []).append(name)
    return partition


def merge_partition_engine_c_ladder(
    partition: dict[tuple[str, str], list[str]],
    min_lifters: int = MIN_LIFTERS_PER_CELL,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Apply Engine C's bracket-merge ladder to the lifter partition.

    Mirrors ``backend.app.athlete_projection._build_division_cells``: within
    each age division, walk brackets low->high and merge sparse buckets
    upward (then downward) until each merged group reaches ``min_lifters``.
    A whole division below the floor collapses to one division-global cell.

    Returns a dict keyed by (division, anchor_bracket) with payload:
      ``lifters``       -- combined list of lifter names
      ``merged_from``   -- tuple of bracket labels merged into this group
      ``is_global``     -- True if the whole division was below the floor
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    brackets = list(GLP_BRACKET_LABELS)

    for division in ap.AGE_DIVISIONS:
        # Pull all lifters in this division across all brackets.
        per_bracket: dict[str, list[str]] = {
            b: list(partition.get((division, b), [])) for b in brackets
        }
        total_in_div = sum(len(v) for v in per_bracket.values())
        if total_in_div == 0:
            continue

        # Whole-division fallback when the division is too small.
        if total_in_div < min_lifters:
            all_names: list[str] = []
            for b in brackets:
                all_names.extend(per_bracket[b])
            out[(division, brackets[0])] = {
                "lifters": all_names,
                "merged_from": tuple(brackets),
                "is_global": True,
            }
            continue

        # Bracket-level ladder: low -> high, then high -> low for shortfalls.
        assigned = [False] * len(brackets)
        for i in range(len(brackets)):
            if assigned[i]:
                continue
            merged_labels = [brackets[i]]
            accumulated: list[str] = list(per_bracket[brackets[i]])

            j = i + 1
            while len(accumulated) < min_lifters and j < len(brackets):
                if assigned[j]:
                    j += 1
                    continue
                accumulated.extend(per_bracket[brackets[j]])
                merged_labels.append(brackets[j])
                assigned[j] = True
                j += 1

            k = i - 1
            while len(accumulated) < min_lifters and k >= 0:
                if assigned[k]:
                    k -= 1
                    continue
                accumulated = list(per_bracket[brackets[k]]) + accumulated
                merged_labels.insert(0, brackets[k])
                assigned[k] = True
                k -= 1

            assigned[i] = True
            anchor = merged_labels[0]
            out[(division, anchor)] = {
                "lifters": accumulated,
                "merged_from": tuple(merged_labels),
                "is_global": False,
            }

    return out


# =============================================================================
# MixedLM fit
# =============================================================================


def build_cell_frame(
    df: pd.DataFrame, lifter_names: list[str], lift: str
) -> pd.DataFrame:
    """Return long-form DataFrame of all meets for the given lifters that
    contested ``lift``. Columns: lifter_id, years_from_first, lift_kg."""
    lift_col = LIFT_COLS[lift]
    rows: list[dict[str, Any]] = []
    for name in lifter_names:
        meets = df[df["Name"] == name].copy()
        meets = meets[meets[lift_col].notna() & (meets[lift_col] > 0)]
        if len(meets) < 2:
            continue
        dates = pd.to_datetime(meets["Date"].values)
        days = ((dates - dates[0]) / np.timedelta64(1, "D")).astype(float)
        years = days / DAYS_PER_YEAR
        for years_val, kg in zip(years, meets[lift_col].astype(float).values):
            rows.append({
                "lifter_id": name,
                "years_from_first": float(years_val),
                "lift_kg": float(kg),
            })
    return pd.DataFrame(rows)


def fit_cell_mixedlm(cell_df: pd.DataFrame) -> tuple[bool, str | None]:
    """Fit MixedLM on a cell frame; return (converged, failure_mode_or_none).

    Random intercept + slope per lifter, fixed-effect intercept + slope only
    (cell membership is implicit -- we already filtered to the cell). The
    fixed effects don't include age_division x bracket because the frame is
    already cell-scoped.
    """
    # Lazy import keeps probe module-load cheap when --help is invoked.
    import statsmodels.formula.api as smf  # noqa: PLC0415
    from statsmodels.tools.sm_exceptions import ConvergenceWarning  # noqa: PLC0415

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            md = smf.mixedlm(
                "lift_kg ~ years_from_first",
                cell_df,
                groups=cell_df["lifter_id"],
                re_formula="~years_from_first",
            )
            result = md.fit(method="lbfgs", maxiter=MAXITER)

        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            return False, "did_not_converge"

        if not getattr(result, "converged", True):
            return False, "did_not_converge"

        cov_re = np.asarray(result.cov_re)
        if cov_re.size:
            eigs = np.linalg.eigvalsh(cov_re)
            if np.min(eigs) < 1e-6:
                return False, "boundary_re_cov"

        re = result.random_effects
        if re:
            slopes = [
                float(v.get("years_from_first", 0.0))
                for v in re.values()
            ]
            if slopes and float(np.std(slopes)) < 1e-6:
                return False, "degenerate_blups"

        return True, None
    except np.linalg.LinAlgError:
        return False, "singular_hessian"
    except Exception as exc:  # noqa: BLE001 -- catch-all is the point
        logger.warning("Unexpected exception in cell fit: %s", exc)
        return False, "unexpected_exception"


def run_cell(
    df: pd.DataFrame,
    cell_lifters: list[str],
    cell: tuple[str, str],
    lift: str,
    merged_from: tuple[str, ...] = (),
    is_global: bool = False,
) -> CellFitOutcome | None:
    """Build the cell frame and fit. Returns None when the cell does not
    meet the lifter / meet floor (skipped, not failed)."""
    cell_df = build_cell_frame(df, cell_lifters, lift)
    n_lifters = cell_df["lifter_id"].nunique()
    n_meets = len(cell_df)
    if n_lifters < MIN_LIFTERS_PER_CELL or n_meets < MIN_MEETS_PER_CELL:
        return None

    t0 = time.perf_counter()
    converged, failure_mode = fit_cell_mixedlm(cell_df)
    runtime_s = time.perf_counter() - t0

    if runtime_s > SLOW_FIT_THRESHOLD_S:
        logger.warning(
            "Slow fit: cell=%s lift=%s runtime=%.1fs",
            cell, lift, runtime_s,
        )

    return CellFitOutcome(
        cell_key=(cell[0], cell[1], lift),
        n_lifters=n_lifters,
        n_meets=n_meets,
        runtime_s=runtime_s,
        converged=converged,
        failure_mode=failure_mode,
        merged_from=merged_from if merged_from else (cell[1],),
        is_global_fallback=is_global,
    )


# =============================================================================
# Pass driver
# =============================================================================


def run_pass(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    min_meets: int,
    sample_size: int,
    merge_strategy: str = "none",
    max_lifters: int | None = None,
) -> PassResult:
    logger.info("[%s] selecting lifters with >= %d meets", name, min_meets)
    df = select_lifters_with_floor(conn, min_meets=min_meets)
    if df.empty:
        logger.warning("[%s] no eligible lifters; pass skipped", name)
        return PassResult(
            name=name, min_meets=min_meets, n_lifters_sampled=0,
            merge_strategy=merge_strategy,
        )

    n = sample_size if max_lifters is None else min(sample_size, max_lifters)
    lifter_names = sample_lifters(df, n=n)
    logger.info("[%s] sampled %d lifters", name, len(lifter_names))

    partition = build_cell_partition(df, lifter_names)

    if merge_strategy == "engine-c-ladder":
        merged = merge_partition_engine_c_ladder(
            partition, min_lifters=MIN_LIFTERS_PER_CELL,
        )
        # Treat each merged cell as one fit; "fittable" floor already met by
        # the ladder unless the whole division was still below floor (kept
        # but marked is_global -- expected to converge poorly).
        fittable_cells = [
            (cell, payload["lifters"], payload["merged_from"], payload["is_global"])
            for cell, payload in merged.items()
        ]
        logger.info(
            "[%s] %d raw cells -> %d merged cells via engine-c-ladder",
            name, len(partition), len(merged),
        )
    elif merge_strategy == "none":
        fittable_cells = [
            (cell, lifters, (cell[1],), False)
            for cell, lifters in partition.items()
            if len(lifters) >= MIN_LIFTERS_PER_CELL
        ]
        logger.info(
            "[%s] %d non-empty cells, %d clear the >= %d-lifter floor",
            name, len(partition), len(fittable_cells), MIN_LIFTERS_PER_CELL,
        )
    else:
        raise ValueError(f"unknown merge_strategy: {merge_strategy!r}")

    outcomes: list[CellFitOutcome] = []
    for (cell, cell_lifters, merged_from, is_global) in fittable_cells:
        for lift in LIFT_KEYS:
            outcome = run_cell(
                df, cell_lifters, cell, lift,
                merged_from=merged_from, is_global=is_global,
            )
            if outcome is None:
                continue
            outcomes.append(outcome)
            logger.info(
                "[%s] cell=%s lift=%s n_lifters=%d n_meets=%d merged_from=%s "
                "runtime=%.1fs converged=%s failure=%s",
                name, cell, lift, outcome.n_lifters, outcome.n_meets,
                outcome.merged_from, outcome.runtime_s, outcome.converged,
                outcome.failure_mode,
            )

    return PassResult(
        name=name,
        min_meets=min_meets,
        n_lifters_sampled=len(lifter_names),
        merge_strategy=merge_strategy,
        cell_outcomes=outcomes,
    )


# =============================================================================
# Decision gate
# =============================================================================


def derive_verdict(passes: list[PassResult]) -> dict[str, Any]:
    rates: dict[str, float | None] = {}
    for p in passes:
        d = p.as_dict()
        rates[p.name] = d["overall_convergence_rate"]

    p1 = rates.get("p1_min15_meets")
    p2 = rates.get("p2_min5_meets")

    def gate(rate: float | None) -> str:
        if rate is None:
            return "no_data"
        if rate >= 0.90:
            return "pass"
        if rate >= 0.70:
            return "mixed"
        return "fail"

    p1_band = gate(p1)
    p2_band = gate(p2)

    if p1_band == "pass" and p2_band == "pass":
        verdict = "B-2_cleared"
        recommendation = (
            "Engine D probe PASSED both passes. Session B-2 cleared to wire "
            "MixedLM into mixed_effects_projection and flip MethodPill "
            "disabled: false."
        )
    elif p1_band == "pass" and p2_band == "mixed":
        verdict = "B-2_blocked_p2_mixed"
        recommendation = (
            "Engine D probe MIXED -- clean on mature lifters, weak on "
            "realistic floor. Regularized-GLM fallback scoping needed before "
            "B-2."
        )
    elif p1_band == "fail" or p2_band == "fail":
        verdict = "engine_d_kill_candidate"
        recommendation = (
            "Engine D probe FAILED. Recommend killing Engine D -- MethodPill "
            "copy change to 'discontinued -- Engine C is the production "
            "model' should be scheduled."
        )
    else:
        verdict = "ambiguous"
        recommendation = (
            "Probe outcome did not match a canned verdict; review "
            "per-pass numbers manually."
        )

    return {
        "p1_overall": p1,
        "p2_overall": p2,
        "p1_band": p1_band,
        "p2_band": p2_band,
        "verdict": verdict,
        "recommendation": recommendation,
    }


# =============================================================================
# Driver
# =============================================================================


def get_git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def run_probe(
    input_path: Path,
    output_path: Path,
    which_pass: str = "both",
    merge_strategy: str = "none",
    max_lifters: int | None = None,
) -> dict[str, Any]:
    logger.info(
        "Loading parquet: %s (merge_strategy=%s)",
        input_path, merge_strategy,
    )
    conn = load_parquet_into_duckdb(input_path)

    passes_to_run: list[tuple[str, int]] = []
    if which_pass in ("1", "both"):
        passes_to_run.append(("p1_min15_meets", 15))
    if which_pass in ("2", "both"):
        passes_to_run.append(("p2_min5_meets", 5))

    pass_results: list[PassResult] = []
    for (name, min_meets) in passes_to_run:
        result = run_pass(
            conn,
            name=name,
            min_meets=min_meets,
            sample_size=SAMPLE_SIZE,
            merge_strategy=merge_strategy,
            max_lifters=max_lifters,
        )
        pass_results.append(result)

    artifact = {
        "probe_version": 2,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": get_git_sha(),
        "config": {
            "sample_size": SAMPLE_SIZE,
            "min_lifters_per_cell": MIN_LIFTERS_PER_CELL,
            "min_meets_per_cell": MIN_MEETS_PER_CELL,
            "maxiter": MAXITER,
            "slow_fit_threshold_s": SLOW_FIT_THRESHOLD_S,
            "seed": SEED,
            "merge_strategy": merge_strategy,
        },
        "passes": [p.as_dict() for p in pass_results],
        "decision_gate": derive_verdict(pass_results),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    logger.info("Wrote probe artifact: %s", output_path)
    return artifact


def main() -> None:
    p = argparse.ArgumentParser(
        description="Engine D MixedLM convergence probe (Path A).",
    )
    p.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed" / "openipf.parquet",
        help="Parquet path (defaults to the Canada+IPF preprocess output).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "processed" / "mixedlm_convergence_probe.json",
        help="Where to write the JSON artifact (gitignored by default).",
    )
    p.add_argument(
        "--pass",
        dest="which_pass",
        choices=("1", "2", "both"),
        default="both",
        help="Which sample pass(es) to run.",
    )
    p.add_argument(
        "--merge-strategy",
        choices=("none", "engine-c-ladder"),
        default="none",
        help=(
            "Cell-merge strategy. 'none' fits each (division, bracket) cell "
            "as-is (baseline). 'engine-c-ladder' merges sparse brackets "
            "within a division until each merged cell hits the lifter "
            "floor, mirroring _build_division_cells in production code."
        ),
    )
    p.add_argument(
        "--max-lifters",
        type=int,
        default=None,
        help="Optional cap for fast smoke runs.",
    )
    args = p.parse_args()

    if not args.input.exists():
        logger.error("Input parquet not found: %s", args.input)
        sys.exit(1)

    artifact = run_probe(
        input_path=args.input,
        output_path=args.output,
        which_pass=args.which_pass,
        merge_strategy=args.merge_strategy,
        max_lifters=args.max_lifters,
    )

    gate = artifact["decision_gate"]
    logger.info(
        "Verdict: %s (p1=%s p2=%s)",
        gate["verdict"], gate["p1_overall"], gate["p2_overall"],
    )
    logger.info("Recommendation: %s", gate["recommendation"])


if __name__ == "__main__":
    main()
