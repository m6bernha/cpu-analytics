# ADR 0004: Long-horizon backtest and the Engine C to Gompertz cascade

- Status: accepted
- Date: 2026-08-09
- Resolves the standing backlog item "Gompertz baseline evaluation --
  v2 candidate" in `NEXT_STEPS.md`, captured 2026-05-20.
- Numbers here are the run committed as `data/backtest_results.json`.
  Reproduce with:

  ```
  OPENIPF_CSV=<openipf CSV> python data/preprocess.py --no-scope-filter
  python data/backtest_projection.py \
      --input data/processed/openipf_global.parquet \
      --output data/backtest_results.json
  ```

## Context

`NEXT_STEPS.md` has carried a standing rule since 2026-05-20: **do not
implement a Gompertz cascade without a numerical reading at 24 months or
beyond, because the widening-margin trend may not hold.** This ADR
supplies that reading.

The evidence it was to be judged against looked like this:

| Horizon | Engine C MAPE | Gompertz MAPE | Gompertz win |
|---|---|---|---|
| 3 mo | 3.95% | 3.65% | +0.30 pp |
| 6 mo | 4.48% | 3.97% | +0.51 pp |
| 12 mo | 5.27% | 4.42% | +0.85 pp |
| 18 mo | 6.69% | 5.06% | +1.63 pp |

Before reading anything into a fresh 24/36-month row, that table had to be
re-earned. The harness that produced it had four defects, three of which
push in the same direction, plus a fifth found while cross-checking the
new numbers.

### Defect 1: the harness did not run Engine C

Engine C, as shipped, projects squat, bench and deadlift independently.
Each lift gets its own current level (max of its last 3 contested
results), its own Huber personal slope, its own shrinkage weight
`n/(n+5)` counting only meets that contested that lift, and its own cohort
cell. The three are then summed.

The harness did none of that. It fit a single Huber slope to the TOTAL
series and combined it with the **squat** cohort cell, annotated in the
source as a "total-level cohort proxy". A squat slope is roughly a third
of a total slope, so the cohort half of the shrinkage was understated
about threefold, and the level was a quantity no production code path
computes. The measured engine was a lookalike.

This is the second time this exact failure mode has hit this subsystem.
The first was the Engine D convergence probe of 2026-04-27, which fitted
MixedLM on bare `(division, bracket)` cells without the production
bracket-merge ladder and returned a "kill" verdict on 3 fits; adding the
ladder flipped convergence from 33% to 91.7% and Engine D shipped.

**Fix:** Engine C now lives in `project_from_history`;
`shrinkage_projection` is a thin loader over it, and the backtest calls
the same function with injected cohort and Kaplan-Meier lookups.
`TestProjectFromHistoryIsTheSameEngine` locks the delegation and
negative-controls the injection point.

### Defect 2: cohort cells were fit on the held-out meets

`_fit_cohort_cells` was called on the full frame. The source comment
justified this by noting that a single lifter barely moves 231 cells,
which is true and beside the point: *every* lifter's future was in there,
so the cohort slopes used to predict the held-out meets were partly fit on
those very meets.

**Fix:** cells are fit on the concatenated training portions only.

### Defect 3: the scoring tolerance biased the horizon trend

The harness predicted at a nominal horizon and scored against any held-out
meet within +/- 90 days. At 3 months that window is the entire horizon; at
36 months it is 8 percent of it. The result is a date-mismatch error that
shrinks as the horizon grows, which inflates apparent accuracy at long
horizons for every engine. Since the decision rule is literally "does the
margin widen with horizon", the instrument was biased along the exact axis
being measured.

**Fix:** each held-out meet is scored at its real date, and buckets group
results afterwards rather than defining the prediction target.

### Defect 4 in the reading, not the harness: unpaired comparison

Gompertz only answers when `curve_fit` converges, so it declines the
careers hardest to fit. Its MAPE was computed on ~75% of Engine C's
sample and then printed in an adjacent column, which invites exactly the
comparison the numbers cannot support.

**Fix:** every cross-engine claim is computed on the observations where
both engines answered, with a bootstrap interval resampled by lifter.
Own-sample MAPEs are still published, labelled non-comparable.

### Defect 5: the harness was not reproducible

Found while cross-checking two runs that should have matched. 1,664
lifter-days in the eligible pool carry more than one Raw SBD row, and the
production cohort fitter assigns each lifter a GLP bracket from
`groupby("Name").tail(1)` over a frame ordered by `(Name, Date)`. With
tied sort keys under multi-threaded DuckDB, which row landed last moved
between runs, a handful of lifters changed bracket, and reported MAPE
wandered by up to about 0.15 pp. Far below the effects measured here, but
a decision document whose numbers cannot be reproduced is not worth
defending.

**Fix:** `fit_cohort_cells_from_frame` sorts on a full key and pins
`threads=1` with `preserve_insertion_order`. Verified by running the
harness twice end to end on the same input: the artifact and the
observations dump are now **byte-identical** across runs. The first
hypothesis for this variation was wrong, so it was settled by a controlled
double run rather than by argument.

## Method

- **Split.** Every career is cut 36 months before its final meet. Meets at
  or before the cut train; later meets are held out. Requires at least 15
  career meets and at least 5 training meets, the latter matching
  production's `SMALL_N_THRESHOLD` so the measured regime is the one where
  production does not clamp the horizon to 6 months.
- **Scoring.** Each held-out meet is bucketed by elapsed months from the
  last training meet into 3 / 6 / 12 / 18 / 24 / 36-month buckets, one
  observation per lifter per bucket, and the engines predict at that
  meet's exact date.
- **Pool.** Global OpenIPF export, not the Canada+IPF production scope,
  for sample size. Cohort fitting runs the production fitter over that
  pool.
- **Comparison.** Paired mean difference in absolute percentage error,
  with a 2,000-resample percentile bootstrap clustered on lifter.
- **Controls.** Alongside log-linear and Gompertz, a naive persistence
  baseline ("no change from last meet") is scored. Gompertz saturates and
  Engine C does not, so on plateaued careers Gompertz wins partly by
  predicting less growth. If naive persistence also beats Engine C at long
  horizons, the finding is that Engine C over-extrapolates, and the cheap
  fix is slope damping rather than a second engine.

The 24 and 36-month readings are diagnostic only. The UI caps projections
at 18 months and this ADR does not propose changing that.

## Results

Global OpenIPF pool, 1,635 lifters with 15+ Raw SBD meets. 1,470 survived
the split (89 rejected for too few training meets, 76 with no held-out meet
in any bucket), giving 5,581 scored observations.

### Engine C is biased, and the bias is nearly its entire error

Signed error, positive meaning the engine projected above what the lifter
actually totalled:

| Engine | 3 mo | 6 mo | 12 mo | 18 mo | 24 mo | 36 mo |
|---|---|---|---|---|---|---|
| Engine C | +2.20% | +3.49% | +5.09% | +6.13% | +9.25% | +12.06% |
| Log-linear | +1.89% | +3.75% | +5.67% | +7.43% | +11.12% | +16.07% |
| Gompertz | -0.86% | -0.21% | +0.37% | -0.91% | +0.27% | +0.40% |
| No change from last meet | -1.62% | -1.55% | -1.67% | -2.63% | -1.63% | -2.65% |
| Engine C's level, no slope | +1.00% | +0.92% | +0.86% | -0.13% | +1.00% | +0.11% |

Set against Engine C's own MAPE of 12.72% at 36 months, a bias of +12.06%
means the error is not noise. It is almost entirely one-directional
overshoot, and it grows monotonically with horizon. At 12 months, a horizon
the app actually serves, Engine C runs about 5% high, which on a 500 kg
total is roughly 25 kg.

### Gompertz beats Engine C, and so does doing nothing

Paired, on observations where both engines answered, with a 2,000-resample
bootstrap clustered on lifter. Negative means the challenger was closer:

| Horizon | Gompertz vs Engine C | 95% CI | No change vs Engine C | 95% CI |
|---|---|---|---|---|
| 3 mo | -0.02 pp | -0.35 to +0.30 | +0.34 pp | -0.10 to +0.79 |
| 6 mo | -0.68 pp | -1.00 to -0.35 | -0.32 pp | -0.67 to +0.04 |
| 12 mo | -1.28 pp | -1.69 to -0.79 | -1.02 pp | -1.40 to -0.64 |
| 18 mo | -1.53 pp | -2.19 to -0.75 | -1.33 pp | -1.80 to -0.86 |
| 24 mo | -2.88 pp | -3.64 to -2.08 | -2.81 pp | -3.30 to -2.32 |
| 36 mo | -5.59 pp | -6.32 to -4.77 | -5.44 pp | -6.01 to -4.82 |

The widening-margin trend the backlog asked about is real and it continues
well past 18 months. But it is not evidence for Gompertz. **Predicting that
the lifter never improves again captures nearly the whole margin**: 5.44 pp
of Gompertz's 5.59 pp advantage at 36 months, 2.81 of 2.88 at 24 months.
Gompertz's marginal contribution over a constant is inside the noise at
every horizon.

Log-linear remains worse than Engine C everywhere, by +0.96 pp at 3 months
widening to +5.83 pp at 36, consistent with the earlier reading.

Gompertz coverage is 68-70%, not the ~75% the backlog assumed, so a cascade
would leave nearly a third of lifters on the unmodified Engine C path.

### Gompertz does not beat the constant

Paired directly against "no change from last meet", on the observations
where Gompertz converged:

| Horizon | Gompertz vs no change | 95% CI | Gompertz win rate |
|---|---|---|---|
| 3 mo | -0.40 pp | -0.86 to -0.00 | 54.0% |
| 6 mo | -0.22 pp | -0.50 to +0.05 | 53.1% |
| 12 mo | +0.14 pp | -0.23 to +0.56 | 52.0% |
| 18 mo | +0.29 pp | -0.27 to +0.96 | 54.3% |
| 24 mo | +0.46 pp | -0.16 to +1.11 | 51.6% |
| 36 mo | **+0.91 pp** | **+0.35 to +1.54** | 52.4% |

Gompertz is indistinguishable from a constant at 6 through 24 months and
**significantly worse than a constant at 36 months**. Its only advantage is
at 3 months, where the interval barely clears zero. Its entire apparent win
over Engine C was Engine C's overshoot, not Gompertz's curve.

### The overshoot is the slope, not the level

Engine C's level is the sum of each lift's max-of-last-3, an upper envelope
that no single meet need have hit. That was the natural suspect. It is not
the culprit:

| Engine | 12 mo bias | 36 mo bias | 12 mo MAPE | 36 mo MAPE |
|---|---|---|---|---|
| Engine C (level + slope) | +5.09% | +12.06% | 6.01% | 12.72% |
| Engine C's level, no slope | +0.86% | +0.11% | 4.76% | 7.07% |
| Last actual total, no slope | -1.67% | -2.65% | 4.99% | 7.28% |

Holding Engine C's own level constant is **the most accurate predictor in
the entire comparison at every horizon**, and it is very nearly unbiased.
The level convention is well calibrated, and is in fact better than using
the last actual total, which runs low. Essentially all of Engine C's
overshoot comes from projecting its slope forward.

### It is not an artifact of the pool

Two checks, both run against the observations dump rather than a re-run:

- **Career-final meets.** Holding out the last 36 months enriches the long
  buckets for a lifter's last-ever meet, where predicting no growth could
  win for the wrong reason. Excluding all 688 such observations moves
  Engine C's 36-month bias from +12.06% to +11.66%. The effect is not
  driven by retirements.
- **Career stage.** The overshoot is *worse* for lifters who were still
  adding weight over their training window, at least 5 kg/year (+13.63% at
  36 months), than for those already flat or declining (+6.88%). The
  concern was that a plateau-heavy pool made Engine C look bad; the
  opposite is true. Engine C over-extrapolates hardest for exactly the
  lifters whose recent history looks strongest, which is also the group
  most likely to open the projection tab.

The same check rules out zeroing the slope as the fix. For lifters with 8
or fewer training meets, a flat prediction runs 6.93% **low** at 36 months
while Engine C runs 11.86% high. Newer lifters do improve. The correct
change is to damp the slope, not to remove it.

Both checks are reproducible from the committed run without re-scoring:
the harness writes `data/backtest_results_observations.jsonl` (gitignored)
carrying every per-observation prediction, and the stratification is a join
against the parquet on lifter name.

## Decision

**No-go on the Engine C to Gompertz cascade.** Rejected on the evidence,
not deferred:

1. Gompertz's advantage over Engine C is not Gompertz's. A constant
   captures 5.44 of its 5.59 pp margin at 36 months.
2. Head to head against that constant, Gompertz is inside the noise from 6
   to 24 months and significantly worse at 36.
3. It answers for only 68-70% of lifters, so a third would stay on the
   unfixed path.
4. It would cost per-lifter `curve_fit` at precompute time and a
   re-derivation of Engine D's cohort layer, whose MixedLM is linear in
   time and does not port to a nonlinear fit.

**Go on damping Engine C's projected slope**, scheduled as the next
projection session. Engine C's level convention is kept unchanged: it is
already the best-calibrated component measured here. The shape should be a
saturating slope, so that the projected gain approaches an asymptote rather
than growing linearly, which preserves near-term behaviour, keeps 100%
coverage, needs no per-lifter nonlinear fit, and drops into the existing
per-segment projection loop. Engine D supplies a slope to the same
machinery, so it inherits the fix rather than needing its own.

### Ship gates for the damping change

Measured on this harness, global pool, paired and bootstrapped as above.
Current values are from the run committed with this ADR.

| Gate | Limit | Engine C today |
|---|---|---|
| Absolute bias at 12 months | <= 2.0 pp | +5.09 pp FAIL |
| Absolute bias at 18 months | <= 2.0 pp | +6.13 pp FAIL |
| Absolute bias at 12 months, lifters with <= 8 training meets | <= 4.0 pp | +4.10 pp FAIL, marginally |
| Paired loss to "level, no slope" at 12 and 18 months | <= 0 pp, or CI spanning 0 | -1.25 / -1.79 pp FAIL |
| MAPE at 6 months | <= 6.0% | 4.45% pass |
| MAPE at 12 months | <= 12.0% | 6.01% pass |

The third row is the guard against overcorrecting: a change that damps the
slope to nothing would pass the first two gates and start under-predicting
newer lifters, whose projections are the ones that should show growth.

**The existing gates were the wrong instrument and are superseded.** All
three of them pass today, on an engine that runs 5 to 6 percent high at
both horizons the app serves, because every one of them measures the
magnitude of the error and none measures its direction. A systematically
biased engine is invisible to a MAPE threshold. That is why bias gates lead
the table above.

### Not decided here

The 18-month UI cap stays. Nothing in these numbers argues for offering a
longer horizon, and the 24 and 36 month readings exist only to expose the
divergence.

Whether the damping constant should vary by age division or GLP bracket is
left to the implementation session. The stratification above shows the
overshoot varies substantially by career stage, so a single global constant
may not be enough, but that is a question to settle by fitting rather than
by argument.
