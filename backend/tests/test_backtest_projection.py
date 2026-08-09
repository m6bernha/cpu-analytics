"""Tests for the offline Athlete Projection backtest harness.

The harness is not imported by any production module and does not run in
CI, so it is tempting to leave it untested. That is exactly backwards: its
output is a committed artifact that the About page renders as fact, and it
is the sole evidence behind the Engine C to Gompertz cascade decision. A
harness that is quietly wrong produces a confident number nobody can
falsify by looking at the site.

The four properties locked here are the ones that were wrong, or absent,
in the version that produced the numbers shipped before 2026-08-09:

  1. Horizon bucketing is contiguous and non-overlapping, and one lifter
     contributes at most one observation per bucket.
  2. The train/holdout split never lets a held-out meet into training.
  3. Head-to-head comparison is PAIRED. The negative control is the case
     that motivated it: an engine that declines the hard observations
     looks better than the baseline on raw MAPE while being worse on every
     observation the two actually share.
  4. The bootstrap resamples LIFTERS, not rows, so correlated observations
     from one lifter do not masquerade as independent evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Make the ``data`` package importable from inside backend/tests/.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from data.backtest_projection import (  # noqa: E402
    ENGINE_KEYS,
    HOLDOUT_SPAN_MONTHS,
    HORIZON_BUCKETS,
    HORIZONS_MONTHS,
    MIN_TRAIN_MEETS,
    SHIP_GATES,
    Observation,
    _cluster_bootstrap_ci,
    bucket_for,
    build_artifact,
    head_to_head,
    select_scoring_meets,
    split_train_holdout,
    summarize_engine,
)


# ---------------------------------------------------------------------------
# Horizon bucketing
# ---------------------------------------------------------------------------


def test_buckets_are_contiguous_and_cover_every_declared_horizon():
    assert [h for h, _lo, _hi in HORIZON_BUCKETS] == list(HORIZONS_MONTHS)
    for (_h1, _lo1, hi1), (_h2, lo2, _hi2) in zip(HORIZON_BUCKETS, HORIZON_BUCKETS[1:]):
        assert hi1 == lo2, "buckets must be contiguous, or meets fall in the gap"


@pytest.mark.parametrize(
    "elapsed_months,expected",
    [
        (0.0, None),      # same-training-block noise
        (1.4, None),
        (1.5, 3),         # lower edge is inclusive
        (4.49, 3),
        (4.5, 6),         # upper edge belongs to the next bucket
        (8.9, 6),
        (12.0, 12),
        (20.99, 18),
        (21.0, 24),
        (29.9, 24),
        (30.0, 36),
        (41.9, 36),
        (42.0, None),     # past the last bucket, nothing to answer for
        (120.0, None),
    ],
)
def test_bucket_for_edges(elapsed_months, expected):
    assert bucket_for(elapsed_months) == expected


def test_every_bucket_is_reachable_within_the_holdout_span():
    """The holdout span has to be long enough to contain the longest bucket.

    If HOLDOUT_SPAN_MONTHS were shortened below the last bucket's lower
    edge, the 36-month row would silently report n=0 rather than fail.
    """
    longest_bucket_start = HORIZON_BUCKETS[-1][1]
    assert HOLDOUT_SPAN_MONTHS >= longest_bucket_start


# ---------------------------------------------------------------------------
# Train / holdout split
# ---------------------------------------------------------------------------


def _career(dates: list[str], totals: list[float] | None = None) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame({
        "Name": ["Test Lifter"] * n,
        "Date": pd.to_datetime(dates),
        "TotalKg": totals if totals is not None else [400.0 + 5 * i for i in range(n)],
    })


def test_split_puts_the_final_holdout_span_on_the_holdout_side():
    dates = [f"201{y}-01-15" for y in range(0, 10)]
    train, holdout = split_train_holdout(_career(dates))

    cut = pd.to_datetime(dates[-1]) - pd.DateOffset(months=HOLDOUT_SPAN_MONTHS)
    assert pd.to_datetime(train["Date"]).max() <= cut
    assert pd.to_datetime(holdout["Date"]).min() > cut
    # No meet may appear on both sides.
    assert set(train["Date"]).isdisjoint(set(holdout["Date"]))
    assert len(train) + len(holdout) == len(dates)


def test_split_rejects_a_career_with_too_few_training_meets():
    # Everything inside the holdout window: nothing left to train on.
    assert split_train_holdout(_career(["2024-01-01", "2024-06-01", "2025-01-01"])) is None


def test_split_rejects_when_training_is_one_short_of_the_floor():
    dates = [f"2010-0{i}-01" for i in range(1, MIN_TRAIN_MEETS)] + ["2020-01-01"]
    assert split_train_holdout(_career(dates)) is None


def test_split_rejects_a_career_with_nothing_held_out():
    dates = ["2010-01-01", "2010-06-01", "2011-01-01", "2011-06-01", "2012-01-01"]
    assert split_train_holdout(_career(dates)) is None


# ---------------------------------------------------------------------------
# Scoring-meet selection
# ---------------------------------------------------------------------------


def test_one_observation_per_bucket_and_the_closest_meet_wins():
    train = _career(["2015-01-01", "2015-06-01", "2016-01-01", "2016-06-01", "2017-01-01"])
    # Two meets land in the 12-month bucket (9.0 <= elapsed < 15.0). The one
    # nearer to 12 months must win; otherwise a lifter double-counts and the
    # cluster bootstrap sees a distorted lifter -> observations mapping.
    holdout = _career(
        ["2017-11-01", "2018-01-05", "2020-01-10"],
        totals=[500.0, 510.0, 520.0],
    )
    scored = select_scoring_meets(train, holdout)

    by_horizon = {h: (elapsed, total) for h, elapsed, total in scored}
    assert by_horizon[12][1] == 510.0, "the meet closest to 12 months should win"
    assert len(scored) == len({h for h, _e, _t in scored}), "buckets must be unique"


def test_scoring_meets_ignore_null_and_nonpositive_totals():
    train = _career(["2015-01-01", "2015-06-01", "2016-01-01", "2016-06-01", "2017-01-01"])
    holdout = _career(["2018-01-05"], totals=[None])
    assert select_scoring_meets(train, holdout) == []

    holdout_zero = _career(["2018-01-05"], totals=[0.0])
    assert select_scoring_meets(train, holdout_zero) == []


def test_elapsed_is_measured_from_the_last_training_meet():
    train = _career(["2015-01-01", "2015-06-01", "2016-01-01", "2016-06-01", "2017-01-01"])
    holdout = _career(["2018-01-01"], totals=[500.0])
    (_horizon, elapsed, _total), = select_scoring_meets(train, holdout)
    assert elapsed == pytest.approx(12.0, abs=0.2)


# ---------------------------------------------------------------------------
# Paired comparison
# ---------------------------------------------------------------------------


def _obs(name: str, horizon: int, actual: float, **preds: float) -> Observation:
    return Observation(
        name=name, horizon=horizon, elapsed_months=float(horizon),
        actual_total=actual, predictions=dict(preds),
    )


def test_unpaired_mape_can_disagree_with_the_paired_verdict():
    """The negative control for the whole comparison design.

    `selective` answers only the two easy observations and declines the two
    hard ones, exactly as Gompertz declines whenever curve_fit does not
    converge. On its own sample it posts a far better MAPE than the
    baseline. On the observations the two actually share it is strictly
    worse. Reporting the first number as a head-to-head result is the
    failure this test exists to catch.
    """
    observations = [
        _obs("easy-1", 12, 100.0, engine_c=101.0, selective=102.0),
        _obs("easy-2", 12, 100.0, engine_c=101.0, selective=102.0),
        _obs("hard-1", 12, 100.0, engine_c=110.0),
        _obs("hard-2", 12, 100.0, engine_c=110.0),
    ]

    own_sample = {
        s["engine"]: s["by_horizon"]["12"]
        for s in (summarize_engine(observations, e) for e in ("engine_c", "selective"))
    }
    assert own_sample["selective"]["mape"] == pytest.approx(2.0)
    assert own_sample["engine_c"]["mape"] == pytest.approx(5.5)
    assert own_sample["selective"]["mape"] < own_sample["engine_c"]["mape"]

    paired = head_to_head(observations, "selective", resamples=200)["by_horizon"]["12"]
    assert paired["n_paired"] == 2
    assert paired["mape_baseline"] == pytest.approx(1.0)
    assert paired["mape_challenger"] == pytest.approx(2.0)
    assert paired["mean_diff"] > 0, "challenger is worse where the two actually overlap"
    assert paired["challenger_win_rate"] == 0.0


def test_coverage_reports_the_share_of_observations_an_engine_answered():
    observations = [
        _obs("a", 12, 100.0, engine_c=101.0, selective=102.0),
        _obs("b", 12, 100.0, engine_c=101.0),
    ]
    summary = summarize_engine(observations, "selective")["by_horizon"]["12"]
    assert summary["coverage"] == pytest.approx(0.5)
    assert summarize_engine(observations, "engine_c")["by_horizon"]["12"]["coverage"] == 1.0


def test_bias_is_signed_where_mape_is_not():
    """Two engines, identical MAPE, opposite bias."""
    observations = [
        _obs("a", 12, 100.0, high=110.0, low=90.0),
        _obs("b", 12, 100.0, high=110.0, low=90.0),
    ]
    high = summarize_engine(observations, "high")["by_horizon"]["12"]
    low = summarize_engine(observations, "low")["by_horizon"]["12"]
    assert high["mape"] == pytest.approx(low["mape"])
    assert high["bias"] == pytest.approx(+10.0)
    assert low["bias"] == pytest.approx(-10.0)


def test_head_to_head_reports_zero_paired_when_engines_never_overlap():
    observations = [
        _obs("a", 12, 100.0, engine_c=101.0),
        _obs("b", 12, 100.0, other=102.0),
    ]
    cell = head_to_head(observations, "other", resamples=50)["by_horizon"]["12"]
    assert cell["n_paired"] == 0
    assert cell["mean_diff"] is None


def test_sign_convention_negative_means_challenger_is_better():
    observations = [_obs("a", 12, 100.0, engine_c=110.0, challenger=101.0)]
    cell = head_to_head(observations, "challenger", resamples=50)["by_horizon"]["12"]
    assert cell["mean_diff"] == pytest.approx(-9.0)
    assert cell["challenger_win_rate"] == 1.0


# ---------------------------------------------------------------------------
# Cluster bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_is_deterministic_for_a_fixed_seed():
    diffs = {f"lifter-{i}": [float(i) - 5.0] for i in range(20)}
    first = _cluster_bootstrap_ci(diffs, resamples=300, seed=7)
    second = _cluster_bootstrap_ci(diffs, resamples=300, seed=7)
    assert first == second


def test_clustering_widens_the_interval_versus_treating_rows_as_independent():
    """One lifter with 20 correlated observations is not 20 lifters.

    Both inputs below hold the same 40 numbers. The clustered layout puts
    them in 2 lifters; the spread-out layout puts them in 40. If the
    bootstrap ignored clusters the two intervals would match, and the
    reported precision would be roughly sqrt(20) times too good.
    """
    clustered = {"lifter-a": [1.0] * 20, "lifter-b": [-1.0] * 20}
    spread = {f"lifter-{i}": [1.0 if i % 2 == 0 else -1.0] for i in range(40)}

    c_low, c_high = _cluster_bootstrap_ci(clustered, resamples=800, seed=11)
    s_low, s_high = _cluster_bootstrap_ci(spread, resamples=800, seed=11)

    assert (c_high - c_low) > (s_high - s_low)


def test_bootstrap_declines_to_guess_from_a_single_lifter():
    assert _cluster_bootstrap_ci({"only": [1.0, 2.0]}, resamples=100, seed=3) == (None, None)


# ---------------------------------------------------------------------------
# Artifact shape
# ---------------------------------------------------------------------------


def test_head_to_head_pairs_are_unique():
    """A challenger may appear more than once, but never against the same
    baseline twice.

    The About page renders one table per head-to-head entry. When the
    Gompertz-vs-no-change comparison was added, Gompertz appeared twice and
    the React list was still keyed on the challenger alone, which is a
    duplicate key: React may drop or duplicate a table, and the resulting
    console error failed all seven Playwright smoke tests, because the
    About tab stays mounted behind every other tab. The invariant that
    makes the key safe belongs here, at the source of the list.
    """
    observations = [_obs("a", 12, 100.0, engine_c=101.0, gompertz=102.0, flat_last=103.0)]
    artifact = build_artifact(observations, Path("dummy.parquet"), pool_lifters=1)
    pairs = [(h["challenger"], h["baseline"]) for h in artifact["head_to_head"]]
    assert len(pairs) == len(set(pairs)), f"duplicate head-to-head pair in {pairs}"


def test_every_engine_key_is_summarized():
    observations = [_obs("a", 12, 100.0, engine_c=101.0)]
    artifact = build_artifact(observations, Path("dummy.parquet"), pool_lifters=1)
    assert [e["engine"] for e in artifact["summary"]["engines"]] == list(ENGINE_KEYS)


def test_ship_gates_cover_bias_not_just_magnitude():
    """The gate set superseded on 2026-08-09 was all MAPE thresholds, and
    every one of them passed on an engine running 5-6% high at both served
    horizons. At least one gate must constrain the SIGN of the error."""
    assert any("bias" in key for key in SHIP_GATES)
