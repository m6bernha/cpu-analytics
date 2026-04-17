# Next Steps

Living backlog for the cpu-analytics project. Captured 2026-04-16 during the
Batch 1-3 feedback session. When starting a new Claude session, read this
file after `CLAUDE.md`. Cross items off as they land; add new ones as they
arise.

Ordering is a judgment call between impact and effort.

---

## P0 -- Immediate user action (no code)

### Trigger the weekly data-refresh workflow manually

The parquet is now filtered to Canada+IPF at preprocess time (commit
`0f1f691`). The shrink does not take effect in production until the
GitHub Actions workflow regenerates the published parquet.

1. Go to https://github.com/m6bernha/cpu-analytics/actions
2. Open "Refresh OpenIPF data"
3. Click "Run workflow" -> "Run workflow"
4. Wait ~3 minutes
5. Either restart Render manually or wait for next spin-down/up cycle

After that, Render logs show `[startup] process RSS: <MB>` dramatically
lower than before. Expected: well under 200 MB (was 400+ on the full
export).

---

## P1 -- Open bugs / polish still outstanding

### Per-lift progression ignores three filters

`/api/cohort/lift_progression` does NOT thread `age_category`,
`max_gap_months`, or `same_class_only` from the frontend. The UI shows
an amber warning when those filters are active alongside the per-lift
toggle, but that is a workaround, not a fix. Extend
`compute_lift_progression` to accept those three params and apply them
the same way `compute_progression` does.

Files: `backend/app/progression.py`, `backend/app/main.py`,
`frontend/src/lib/api.ts`, `frontend/src/tabs/Progression.tsx`.

### LifterDetail Recharts static import defeats the CompareView split

The parallel agent split CompareView out (commit `19406a4`) but
`LifterDetail` still statically imports `recharts`, so Vite keeps the
~200 KB Recharts library in the main chunk. To claim the full savings,
lazy-load `LifterDetail` too (it's only rendered after a search click).

Files: `frontend/src/tabs/LifterLookup.tsx`.

### QT Squeeze axis + graph titles overlap at some widths

Each Block in QT Squeeze has the chart axis label and the section title
colliding at certain viewport sizes. Fix by adding explicit bottom margin
on the chart container plus top margin on the `<h3>` title.

Files: `frontend/src/tabs/QTSqueeze.tsx`.

### Compare chart visually crushes short-career lifters

When comparing lifters of very different career lengths (eg Matthias
Bernhard with 3 meets over 6 months vs Quinn Baxter with many meets
over multiple years), Matthias's curve collapses to a point on the left
and is unreadable.

Two options, not mutually exclusive:

1. Synchronized x-axis zoom control -- slider that lets user zoom into
   the first N months. Default "all", plus presets for "first 12 mo",
   "first 24 mo", "first 5 years".
2. Small multiples -- when max x-values differ by more than ~4x, render
   separate charts per lifter instead of overlaying.

Files: `frontend/src/tabs/CompareView.tsx`.

### Compare chart tooltip gaps

Recharts' `Tooltip` only shows data at x-values where every series has
a point. Because each lifter's meets are on different calendar dates
(now: months-from-their-own-first-SBD), x-values rarely line up and
hovering between meets shows nothing.

User wants this fixed WITHOUT artificially extrapolating data.

Options:

- Custom tooltip component that finds the NEAREST point per series
  independently and renders them all, even when x-values don't match.
  Moderate work -- Recharts supports custom Tooltip content.
- Voronoi overlay -- not native to Recharts; would mean either a custom
  SVG overlay or swapping chart library for this view.

Files: `frontend/src/tabs/CompareView.tsx`.

### Compare chart data gaps

Compare is the most data-barren page. Add:

- Per-lifter summary cards above the chart (best total, rate kg/month,
  meet count, first-meet date, class migration count, QT status).
- Optionally, QT reference lines for one of the selected lifters'
  classes (user picks, or default to mode across selected lifters).

Files: `frontend/src/tabs/CompareView.tsx`.

---

## P2 -- Feature work still outstanding

### QT Squeeze overhaul (big redesign)

User explicitly asked for this. Current layout has 4 fixed blocks
(F_Regionals, F_Nationals, M_Regionals, M_Nationals) that only show
Open coverage. Replace with a filter panel (Sex, Age division, Weight
class, Equipment) driving a single configurable view.

Data prerequisite: powerlifting.ca/qualifying-standards has the full
per-age-division QT table. Scrape or hand-transcribe into an expanded
`data/qualifying_totals_canpl.csv` with columns for Sex, Level,
Division, WeightClass, QT_pre2025, QT_2025, QT_2027.

Backend: `qt.compute_coverage` and `qt.compute_blocks` need to accept
Division + Equipment parameters. The CASE-WHEN era logic stays.

Frontend: new filter-panel layout matching Progression's visual style.
Retire the 4-block layout.

Estimated effort: 1-2 sessions once the new CSV is in place.

### Manual entry: individual lift inputs

User wants to enter Squat/Bench/Deadlift individually, not just the
Total. The Pydantic schema already has `squat_kg/bench_kg/deadlift_kg`
fields; the frontend form just doesn't surface them. Add 3 number
inputs per meet row; auto-compute total if user leaves total blank
but fills individual lifts.

Files: `frontend/src/tabs/LifterLookup.tsx` (ManualEntryForm).

### Athlete Projection (BETA) tab -- full implementation

Placeholder exists (commit `fd017fe`). Core feature spec:

1. Pick a lifter (search) OR use "current manual entry".
2. Pick a target date.
3. Pick a target QT: Regionals 2025/2027, Nationals 2025/2027, custom.
4. Output: predicted total on target date + confidence interval +
   kg-gap to chosen QT.
5. **Critical UI**: slider between "personal trajectory weight" and
   "cohort average weight". See the math roundtable below -- this
   tab cannot ship numbers until we pick a weighting methodology.

---

## P3 -- Projection weighting roundtable (PRE-SHIP, user input needed)

Open question: **how much weight should individual projection put on a
lifter's own trajectory vs the cohort average for their sex / class /
equipment / age?**

### Candidate methodologies

**A. Pure personal polyfit.**
What we do today for individual projection. Fits a line through the
lifter's SBD meets and extrapolates. Brittle for lifters with 2-3 meets.
Over-trusts noise.

**B. Pure cohort.**
Place the lifter's current best on the cohort curve at their
time-offset. Extrapolate forward using the cohort slope. Ignores
whether this lifter is faster or slower than average.

**C. Bayesian shrinkage (recommended default).**
Start cohort-heavy for low meet counts; shift toward personal as
history accumulates. Common form:

```
weight_personal = n / (n + k)
weight_cohort   = k / (n + k)
```

With shrinkage constant `k = 5`:

| meet count n | personal weight | cohort weight |
|---|---|---|
| 2 | 29% | 71% |
| 5 | 50% | 50% |
| 10 | 67% | 33% |
| 20 | 80% | 20% |

Tunable via the UI slider.

**D. Mixed-effects / partial pooling.**
Real statistical machinery. Substantially more complex. Probably overkill
for v1; revisit once we have user feedback.

### Parameters / design questions requiring answers

1. Which cohort? sex + class + equipment + age-at-projection-time, or
   age-at-current-date? Probably age-at-target-date for Masters
   projections.
2. How to handle lifters whose age puts them in Masters territory at
   the target date? Cohort slope may be flat / negative; don't want to
   project a 35-year-old Open lifter into a decline they haven't
   personally shown.
3. Prediction interval: sum the lifter's residual std + cohort residual
   std in quadrature, or just use the wider of the two?
4. How far ahead is "safe" to project? After what date does the
   confidence band get so wide the output is meaningless?

**Decision gate: user must pick a methodology before any Projection tab
math ships to production.** Until then the tab renders a BETA placeholder.

---

## P4 -- Transparency / methodology writing (no-code, high-value)

Every page needs honest-brokerage disclaimers. Sketch:

### Progression tab

Expand the existing methodology `<details>` block to cover:

- Survivorship bias: lifters who competed once and quit are excluded
- Tail thinning: year-15 points represent 20 lifters vs year-0's 2,500
- Division filter uses alias matching against known CPU variants;
  spelling drift may miss some lifters
- Age column is ~70% NULL; Division (CPU age category) is the primary
  age mechanism now
- Trendline is weighted by lifter count per x-bucket

### Lifter Lookup top-level disclaimer

- All trends, projections, and percentile ranks use Canadian
  IPF-affiliated meet data only. Non-Canadian or non-IPF meets a lifter
  has competed in are NOT reflected.
- QT reference lines are CPU QTs specifically. Other federations differ.
- Lifters sharing the same name in OpenPowerlifting may have merged
  histories -- we cannot disambiguate.
- Projection math is linear regression through SBD meets. Lifters with
  plateaus, breakthroughs, or breaks will see oversimplified output.

### Compare mode disclaimer

- Each lifter's x-axis is anchored to their own first SBD meet, not
  calendar time. Lifters with different career lengths may be hard to
  visualize on a shared axis.
- Hover tooltips show actual meet data; between-meet values are not
  interpolated.

### Manual entry disclaimer

- Projections are based solely on meets you entered. They do NOT blend
  cohort data. Fewer than 5 entered meets -> very noisy projection.

### QT Squeeze methodology note

- Open defined as Division='Open' in OpenPowerlifting.
- 24-month-to-Nationals windows end March 1 of the standard's year.

---

## P5 -- Engineering debt

### Hypothesis property tests for canonical_weight_class

Boundary conditions, NaN inputs, non-M/F sex -- a Hypothesis
`@given(sex=st.sampled_from(['M','F','Mx','']), wc=st.one_of(...))`
loop would catch regressions we haven't imagined. Complements existing
hand-written tests.

### More tests for compute_lift_progression

Currently 2 tests. Add:

- Fixture with mixed-event meets: verify bench-only meets do NOT feed
  per-lift curves (per-lift is SBD-only today)
- Equipment=Equipped aggregation test
- Division=Master 1 alias-matching test

### useUrlState key collision regression test

Dev-only console.warn now. Write a Vitest that renders two components
with overlapping key sets and asserts the warning fires.

### End-to-end smoke test

Manual today. Once Playwright or Cypress is worth the dependency,
smoke-test these routes: `/`, `/?tab=qt`, `/?tab=lookup`, search,
compare deep link, manual entry submit.

---

## P6 -- Strategic questions (not shippable without input)

### Scope expansion to non-IPF Canadian federations?

scope.py hardcodes Country=Canada AND ParentFederation=IPF. CPU is
Canada's IPF affiliate. Question: is there demand for CPU/CPF/WPC/
GPC comparisons? If yes, scope becomes a user-facing toggle and many
computations (QT coverage, cohort progression) need federation-aware
logic.

### Custom domain

`cpu-analytics.vercel.app` is the current URL. Custom domain costs
~$15/year. Candidates: powerlifting.ca subdomain (requires CPU
partnership), or a neutral name like "qtsqueeze.ca" or
"cpuanalytics.ca". No rush.

### Monetization / hosting upgrade

Site is free. If usage grows the Render free tier's 512 MB + cold
starts may be limiting. Options: UptimeRobot keepalive is working;
Render hobby tier is $7/month. A donation link could cover that.
Not pressing.

### More x-axis options in Progression

User asked "What other methods can we display data on the x-axis
aside from what we have already?" Current: Meet #, Days, Weeks,
Months, Years.

Candidate additions:

- **Age**: their age at each meet (noisy due to Age column NULLs).
- **Calendar date**: absolute. Useful for "when did the cohort
  collectively level up" but doesn't align cohorts.
- **Career quartile**: which 25% chunk of their career each meet
  falls in. Normalizes for career length, good for comparing lifters
  at different career stages.
- **Bodyweight bucket**: progression as function of bodyweight.
  Relevant for class migration analysis.

**Career quartile is the most promising. Requires design.**

---

## Reference: commits shipped 2026-04-16

- `25bd798` G1 per-request DuckDB cursors + 4 concurrency tests
- `0f1f691` G2 parquet Canada+IPF filter + SQL aggregation + LRU cache
- `40ff320` G3 HEAD-compatible /api/health + /api/ready + README
- `19406a4` G4 error cards + retry + skeletons + QueryClient defaults
- `fe83169` G5 keepalive GHA + request timing + DuckDB exception handler
- `fd017fe` attribution footer + Athlete Projection BETA placeholder +
  UI polish (reference labels, std dev legend, GLP vs Dots, full lift
  names, pill-nav modes)
- B3 (in progress this commit) data taxonomy: Raw/Equipped, Event
  simplified to Full Power + Bench Only, Division CPU canonical with
  alias map, Age Category (Numeric) dropdown retired
