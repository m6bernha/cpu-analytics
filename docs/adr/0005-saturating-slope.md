# ADR 0005: Saturating slope in Engine C

- Status: accepted
- Date: 2026-08-09
- Implements the "go" half of
  [ADR 0004](0004-projection-engine-cascade.md), which rejected the
  Gompertz cascade and instead scheduled damping Engine C's projected
  slope.
- Numbers are from the run committed as `data/backtest_results.json`.

## Context

ADR 0004 established three things from the offline backtest, on a global
OpenIPF pool of 1,635 lifters:

1. Engine C's error was not noise. Its 36-month MAPE was 12.72% against a
   signed bias of +12.06%, so almost the entire error was one-directional
   overshoot, and it was live at horizons the app serves (+5.09% at 12
   months, +6.13% at 18).
2. The overshoot came from the projected slope, not the level convention.
   Holding Engine C's own level flat with no growth was the most accurate
   predictor tested at every horizon, and very nearly unbiased.
3. Zeroing the slope was nonetheless ruled out, because a flat line
   under-predicted the shortest-history lifters in the pool.

The remaining questions were the functional form and the constant, which
ADR 0004 deferred with the instruction to settle them by fitting rather
than by argument.

## What the data asked for

Two readings from the committed observations dump, neither of which needed
a re-score.

**Engine C's projected gain barely materialised.** Restricted to
observations where it projected a gain of at least 5 kg:

| Horizon | Mean projected gain | Mean realised gain | Median ratio |
|---|---|---|---|
| 3 mo | 10.1 kg | 0.7 kg | 0.00 |
| 6 mo | 16.3 kg | -0.9 kg | 0.05 |
| 12 mo | 26.3 kg | 0.9 kg | 0.10 |
| 18 mo | 38.0 kg | 6.9 kg | 0.20 |
| 24 mo | 51.1 kg | 5.3 kg | 0.17 |
| 36 mo | 73.3 kg | 7.1 kg | 0.12 |

**Zeroing the slope is not equally safe in every stratum.** Bias of
"Engine C's level, held flat" at 12 months:

| Stratum | Bias |
|---|---|
| All | +0.86% |
| Strongly climbing at the cut (>= 15 kg/yr) | -0.74% |
| Short history (<= 8 training meets) | -1.68% |
| Flat or declining at the cut (< 5 kg/yr) | **+4.75%** |

The last row is worth stating plainly because it revises ADR 0004's
framing. For lifters who had already plateaued, the *level* is what runs
high, and the slope is barely involved: Engine C is +5.27% for them while
level-only is +4.75%. Damping the slope cannot fix that group. It is a
separate defect in the max-of-last-3 level convention, and it is not
addressed here.

## Choosing the constant

Six candidates were evaluated in a single scoring pass, as separate
engines. Damping changes only how a fitted slope is spent over time, never
the fit, so with a per-lifter fit cache a six-value sweep costs little more
than one.

Against ADR 0004's gate table:

| tau (days) | bias 12mo | bias 18mo | bias 12mo, short history | vs level-only, 12 / 18mo | MAPE 6mo | MAPE 12mo | gates |
|---|---|---|---|---|---|---|---|
| 30 | +1.21 | +0.21 | -1.22 | -0.06 / -0.13 | 3.65 | 4.69 | 6/6 |
| 45 | +1.38 | +0.38 | -0.99 | -0.09 / -0.18 | 3.65 | 4.67 | 6/6 |
| **60** | **+1.55** | **+0.55** | **-0.76** | **-0.10 / -0.23** | **3.67** | **4.66** | **6/6** |
| 90 | +1.88 | +0.89 | -0.31 | -0.11 / -0.32 | 3.72 | 4.65 | 6/6 |
| 120 | +2.17 | +1.22 | +0.09 | -0.09 / -0.36 | 3.78 | 4.67 | 5/6 |
| 180 | +2.65 | +1.81 | +0.75 | -0.02 / -0.38 | 3.89 | 4.74 | 5/6 |
| none | +5.09 | +6.13 | +4.10 | +1.25 / +1.79 | 4.45 | 6.01 | 2/6 |

120 and 180 fail the 12-month bias gate. Everything from 30 to 90 passes
all six, and their MAPEs are within 0.04 pp of each other, so MAPE does
not decide it.

What decides it is that the passing constants trade one group against
another. A shorter constant suits the numerous long-history lifters; a
longer one suits the climbing and short-history groups, which a short
constant over-damps into under-prediction. Signed bias by stratum:

| Stratum (12 mo) | none | tau=30 | tau=60 | tau=90 | level-only |
|---|---|---|---|---|---|
| Climbing >= 15 kg/yr | +5.64 | -0.22 | +0.29 | +0.79 | -0.74 |
| Climbing 5-15 kg/yr | +3.56 | +1.23 | +1.44 | +1.63 | +1.02 |
| Short history (<= 8 meets) | +4.10 | -1.22 | -0.76 | -0.31 | -1.68 |
| Long history (> 8 meets) | +5.42 | +2.00 | +2.31 | +2.60 | +1.70 |
| Flat or declining | +5.27 | +4.79 | +4.83 | +4.87 | +4.75 |

Taking the worst stratum bias across the 12 and 18 month horizons, and
setting aside the flat-or-declining row for the reason below, tau=60 is
the minimax choice at 2.31 pp, against 2.64 at tau=30, 2.41 at tau=45 and
2.60 at tau=90. It also keeps the most headroom on the tightest gate
while staying within 0.01 pp of the best MAPE.

**Tau = 60 days.**

### One constant is enough, and the reason is not flattering

ADR 0004 asked whether the constant needs to vary by stratum. It does not,
but only because the residual spread is small compared to a defect damping
cannot touch. The flat-or-declining row above moves from +5.27 to +4.83
across the entire sweep: those lifters have almost no slope left, so
damping it changes almost nothing, and their +4.8% bias is the LEVEL. No
choice of tau addresses them. Against that, the ~2.3 pp spread between the
other strata is not worth a second parameter and a second thing to explain
to users.

## Decision

**Projected gain saturates.** Gain at elapsed time `t` is

    slope * tau * (1 - exp(-t / tau))

instead of `slope * t`, so it approaches a ceiling of `slope * tau`. The
instantaneous rate at `t = 0` is still exactly the fitted slope, so the
near term is unchanged in character and only the long tail bends.

Three implementation choices are load-bearing:

- **Applied per segment, as a difference of effective times**, not as one
  closed form over the whole horizon. Engine C re-projects with a
  different cohort slope per segment when a lifter crosses a GLP bracket
  mid-horizon, and only the per-segment form composes correctly under
  that. With a constant slope the segments telescope back to the closed
  form, which is locked by a test.
- **The same effective time replaces elapsed time in the cohort term of
  the prediction interval**, because `d(gain)/d(slope)` is exactly that
  quantity. A band that kept widening linearly under a saturating mean
  would assert the cohort slope could still deliver gains the mean says
  are impossible.
- **The personal term of the interval still uses raw elapsed time.**
  Re-deriving the full prediction interval for the damped mean is out of
  scope here; leaving it produces a band wider than the damped model
  strictly implies, which is the safe direction, and it is documented
  rather than silently mixed.

`SLOPE_DAMPING_TAU_DAYS = None` restores the previous linear behaviour
exactly and is a supported configuration, which is why
`project_from_history` needs a sentinel to distinguish "no damping" from
"caller did not specify".

Engine D feeds a slope into the same projection machinery, so it inherits
the change without needing its own.

## Result

Every gate ADR 0004 set now passes.

| Gate | Limit | Before | After |
|---|---|---|---|
| Bias at 12 months | <= 2.0 pp | +5.09 FAIL | **+1.55 pass** |
| Bias at 18 months | <= 2.0 pp | +6.13 FAIL | **+0.55 pass** |
| Bias at 12 months, <= 8 training meets | <= 4.0 pp | +4.10 FAIL | **-0.76 pass** |
| Paired loss to level-only, 12 / 18 months | <= 0 pp or CI spans 0 | +1.25 / +1.79 FAIL | **-0.10 / -0.23 pass** |
| MAPE at 6 months | <= 6.0% | 4.45 pass | **3.67 pass** |
| MAPE at 12 months | <= 12.0% | 6.01 pass | **4.66 pass** |

Mean absolute percentage error improves at every horizon, which was not
the goal and is worth stating as a consequence rather than a claim:

| Horizon | Before | After |
|---|---|---|
| 3 mo | 3.10% | 2.86% |
| 6 mo | 4.45% | 3.67% |
| 12 mo | 6.01% | 4.66% |
| 18 mo | 6.96% | 4.93% |
| 24 mo | 9.90% | 6.65% |
| 36 mo | 12.72% | 6.86% |

The damped engine also now edges out every baseline in the comparison,
including Gompertz (5.07% at 12 months, 7.89% at 36) and the two trivial
controls, at 100% coverage. That is a by-product of removing a bias, not
evidence that the model got smarter.

### What this looks like to a user

For a lifter around 880 kg with a genuine upward trend over 9 meets, the
projected 12-month gain moves from +25.9 kg to +4.1 kg. For a lifter
already flat it barely moves, +1.3 kg to +0.1 kg. The first number is the
one that will surprise people, so the tab and the About page both explain
it rather than just drawing a flatter line.

## Not decided here

**The level convention is untouched**, and the flat-or-declining stratum
above shows it carries its own +4.75% bias at 12 months. Fixing that means
revisiting max-of-last-3-per-lift-summed, which is a larger change with
its own user-visible consequences, and it deserves its own measurement
rather than being bundled into this one.

**The 18-month UI cap stays.** Nothing here argues for a longer horizon.

**No per-stratum constant.** A single global tau was tried first
deliberately. If it had failed the short-history guard, the next step
would have been making tau a function of meet count, and the fact that it
did not is the reason there is only one number to explain to users.
