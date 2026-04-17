# Next Steps

Living backlog for the cpu-analytics project. Captured 2026-04-16 during the
Batch 1-3 feedback session. When starting a new Claude session, read this
file after `CLAUDE.md`. Cross items off as they land; add new ones as they
arise.

Ordering is a judgment call between impact and effort.

---

## P0 -- Live site is BROKEN (highest priority)

### Filter load failed: age_category

**Symptom**: Progression tab shows "Filter load failed: Filters response
missing or empty: age_category" on cpu-analytics.vercel.app.

**Cause**: Commit `2673ed2` removed `age_category` from the backend filters
response. The matching frontend cleanup (removing it from FiltersResponse,
REQUIRED_FILTER_ARRAYS, ProgressionQuery, and the two guard conditionals
in Progression.tsx) is IN the working tree but NOT committed. Vercel is
deploying origin/main which still references age_category, so frontend
fetches fail validation against the newer backend.

**Fix**: Commit the WIP frontend cleanup (parts of Chat A's per-lift work
cover this) + push. The WIP tree has:
- `frontend/src/tabs/Progression.tsx` (age_category refs removed)
- `frontend/src/lib/api.ts` (age_category field removed)
- Plus `backend/app/progression.py` + tests + conftest.py (per-lift plumbing)

Recommended commit message: `feat(progression): per-lift filter plumbing
+ frontend age_category cleanup (fixes live site)`.

After pushing, Vercel redeploys automatically. Monitor the build at
https://vercel.com/dashboard for the cpu-analytics project.

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

### Per-lift progression ignores three filters — SHIPPED (partial, WIP)

Chat A completed the code. The main.py portion landed in commit `e7432f5`
(which was actually Chat B's QT Squeeze commit; a concurrent hook sweep
captured Chat A's staged main.py). The remaining files are sitting in the
working tree, uncommitted:

- `backend/app/progression.py` (compute_lift_progression accepts the three
  new params with age baseline recomputation)
- `backend/tests/test_progression.py` (8 new tests in TestLiftProgressionFilters)
- `backend/tests/conftest.py` (Ella E fixture for same_class_only)
- `frontend/src/lib/api.ts` (LiftProgressionQuery fields)
- `frontend/src/tabs/Progression.tsx` (query threading + age_category removal)

Verified: local smoke test showed n_lifters 10082 -> 5305 (same_class_only),
5936 (max_gap_months=12), 1048 (age_category=Open). npm run build clean.

Next action: commit these files in a coherent "feat(progression): per-lift
filter plumbing + frontend age_category removal" commit and push.
THIS COMMIT ALSO FIXES THE LIVE-SITE AGE_CATEGORY ERROR.

### LifterDetail Recharts static import defeats the CompareView split

The parallel agent split CompareView out (commit `19406a4`) but
`LifterDetail` still statically imports `recharts`, so Vite keeps the
~200 KB Recharts library in the main chunk. To claim the full savings,
lazy-load `LifterDetail` too (it's only rendered after a search click).

Files: `frontend/src/tabs/LifterLookup.tsx`.

### QT Squeeze axis + graph titles overlap at some widths — SHIPPED

Commit `e7432f5`. XAxis now uses angle=-45 with interval=0, height=56,
tickMargin=6, tick fontSize=11. Dropped the redundant "Weight class (kg)"
axis label (table header already says it). Chart container bumped to h-72.
All 8 weight-class ticks render readably at 360 px width.

Bonus shipped in same commit: age-division dropdown (Sub-Junior through
Master 4), `/api/qt/blocks?division=` param, `using_open_fallback` meta
flag, amber banner when non-Open selected. Data still uses Open values
until `backend/app/data_static/qt_by_division.py` QT_OVERRIDES TODO map
is populated from powerlifting.ca.

### Compare chart short-career blowout + tooltip gaps — SHIPPED

Commit `a6dc701`. X-axis range toggle (All / 6mo / 1y / 2y / 5y) plus an
amber hint at ≥4x career mismatch. Custom nearest-meet tooltip resolves
each series to its closest meet within ±3 months; lifters with no meet
near the hover position drop out rather than reporting gaps. Chip-style
legend above chart replacing default Recharts Legend.

QA'd desktop + 360 px with 4-lifter worst case. Backend tests green in
isolation. NOT yet pushed to origin.

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

### Manual entry: individual lift inputs — SHIPPED

Commit `43c467b`. `total_kg` is optional in `manual.py`; a new
`_reconcile_total_and_lifts` model validator enforces "total only OR all
three lifts", auto-sums when total omitted, rejects mismatches (tol
0.01 kg). Nine test cases in TestTotalAndLiftsReconciliation. Frontend
ManualFormRow adds squat/bench/deadlift inputs on desktop table and
mobile card; total placeholder becomes auto from S/B/D; partial-lift
warning banner blocks submit.

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

### Hypothesis property tests for canonical_weight_class — SHIPPED

Commit `cb7038e`. 19 property tests in
`backend/tests/test_weight_class_properties.py`: return-set membership,
bodyweight monotonicity (M & F), 54-58 kg -> "59" drop-53 regression
guard, 84.5 kg woman -> "84+", invalid sex -> NaN, plus-suffix -> SHW,
bulk-vs-rowwise equivalence. Plus 27 new qt.py edge cases and 22 new
manual.py edge cases, for 68 new tests total. `hypothesis>=6.100` added
to `backend/requirements.txt`. No source edits. 154/154 tests passing.

### More tests for compute_lift_progression — PARTIAL

8 new tests in `backend/tests/test_progression.py`
TestLiftProgressionFilters cover per-lift plumbing of age_category,
max_gap_months, same_class_only. Still want:

- Equipment=Equipped aggregation test (currently only Raw)
- Division=Master 1 alias-matching test for per-lift specifically

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

## Chrome audit 2026-04-17 -- backlog

External exploration of the live site + Vercel + Render + GitHub surfaced 15
distinct issues. The UX triage chat shipped a safe batch in its own session
(Issues 6, 8, 9, 10, 7-partial, 13-verify, 15-verify). Remaining items gated
below.

### Active triage table

| # | Issue | Severity | Effort | Owner | Gate | Status |
|---|---|---|---|---|---|---|
| 1 | Recharts -1x-1 warnings from display:none inactive tabs in App.tsx | high | M shell / L per-chart | TBD | user decides shell vs per-chart | pending decision |
| 2 | /api/health hit every ~5s from one IP | low | S | none (ruled out UptimeRobot) | none | UptimeRobot verified 5min interval, likely Render internal health prober, no action needed unless logs confirm rogue source |
| 3 | Double request logging (timing middleware + uvicorn access log) | medium | S | G1 backend-perf | closed | SHIPPED `1f0b62e` — /api/health suppressed in timing middleware, uvicorn access log retained |
| 4 | No Cache-Control or ETag on weekly-stable JSON endpoints | high | S-M | G1 backend-perf | closed | SHIPPED `1f0b62e` — ETag W/"parquet-<mtime>" + Cache-Control public, max-age=300 on filters, qt/standards, qt/blocks. 304 verified on If-None-Match |
| 5 | No gzip middleware on backend responses | high | S | G1 backend-perf | closed | SHIPPED `1f0b62e` — GZipMiddleware(minimum_size=500), Content-Encoding: gzip verified on qt/blocks |
| 6 | /assets/* hashed bundles served with max-age=0 | high | S | CI-redispatch chat | closed | SHIPPED `12cbb46` — vercel.json headers rule: Cache-Control public, max-age=31536000, immutable |
| 7 | Stale Fly.io references in refresh-data.yml + qt.py comments | polish | S | CI-redispatch chat (partial) + G2 qt sweep | qt.py still outstanding | PARTIAL SHIPPED `12cbb46` — refresh-data.yml scrubbed; qt.py comment sweep still queued |
| 8 | No CI build gate (tsc + build + pytest) on PR/push | blocker | M | CI-redispatch chat | closed | SHIPPED `12cbb46` — .github/workflows/ci.yml with Frontend (tsc + build) and backend pytest jobs, triggers on push + PR to main |
| 9 | refresh-data.yml missing pip cache (~25s/run) | polish | S | CI-redispatch chat | closed | SHIPPED `12cbb46` — setup-python with cache: pip |
| 10 | Deprecated action versions (Node 20 EOL warnings) | polish | S | CI-redispatch chat | closed | SHIPPED `12cbb46` — checkout v4→v6, setup-python v5→v6, action-gh-release v2→v3 |
| 11 | Vercel Skew Protection not enabled | low | strategic | decision | Pro-plan feature ($20/mo), Hobby cannot toggle | PARKED, low traffic hobby project, Pro upgrade not justified |
| 12 | Render free-tier cold start still user-visible (~50s) | medium | L | strategic | user decision | pending user |
| 13 | Verify data.py per-request cursor fix landed cleanly | polish | S read | UX chat | none | verified, no commit needed |
| 14 | LifterLookup.tsx ~44KB, more code-splitting possible | polish | M | G3 LifterDetail lazy-load | push current WIP first | queued |
| 15 | backend/requirements.txt pin discipline check | polish | S | UX chat | none | verified, no commit needed |
| 16 | Local parquet lacks Goodlift column, 503 on /api/lifter/history | high | S | new chat | none | NEW, surfaced by chat C |
| 17 | Concurrent hook sweep captured unrelated staged work in commit `e7432f5` | polish | N/A | retroactive | post-push | NEW, lesson captured in rules |

### Dispatch waves

**Wave 1 user actions, no Claude chat.**
1. Trigger data-refresh GHA (covers existing P0, not a Chrome issue but same
   cadence).
2. Check UptimeRobot monitor interval for cpu-analytics backend (Issue 2).
3. Check Render Settings -> Health Checks interval (Issue 2).
4. Enable Vercel Skew Protection in project settings (Issue 11).

**Wave 2 main-chat decisions.**
- Issue 1: shell fix now (App.tsx unmount inactive, behavior change) vs
  per-chart guard after A+B+C+E merge (safer).
- P3 projection weighting. Still blocker for Athlete Projection math.
- Issue 12: cold-start strategy (keep free + donations, upgrade Render $7/mo,
  migrate to Fly Machines). Not urgent while keepalive holds.

**Wave 3 gated chats (spawn in order after each gate clears).**
1. **G1 backend-perf bundle** — trigger: chat A merged. Files:
   `backend/app/main.py` only. Closes Issues 3 + 4 + 5 together because all
   three want main.py middleware edits.
2. **G2 qt.py comment sweep** — trigger: chat B merged. Files:
   `backend/app/qt.py` comments only. Closes Issue 7 remainder.
3. **G3 LifterDetail lazy-load** — trigger: chat E merged. Files:
   `frontend/src/tabs/LifterLookup.tsx` split, new `LifterDetail.tsx`.
   Closes Issue 14 and the pre-existing P1 "LifterDetail Recharts static
   import" item.
4. **G4 Recharts per-chart guard** — trigger: A+B+C+E all merged, and
   only if user picked the per-chart path in Wave 2. Files: each tab's
   ResponsiveContainer wrapper. Closes Issue 1.
5. **G5 disclaimer copy pass** — trigger: Wave 3 above complete. Covers P4
   items. Must be last because it touches every tab file.

### Rules / lessons captured this session
- Recharts + display:none: inactive tabs that render ResponsiveContainer with a
  zero-height parent fire width=-1 height=-1 warnings. Guard with unmount
  pattern (`{active === id ? <Tab /> : null}`) or inline `display !== 'none'`
  check. Documented in CLAUDE.md Known gotchas.
- CI build-gate on day one: cpu-analytics ran 7 months without a CI build
  gate. Every new web project from here should scaffold a minimal CI
  workflow (tsc + build + test) before first deploy. Documented at
  `~/.claude/rules/common/ci-build-gate.md`.
- Parallel-chat commit hygiene: when five agents stage simultaneously to the
  same worktree, a concurrent hook or agent can sweep an unrelated chat's
  staged files into a mis-labeled commit. The Chat A per-lift main.py change
  landed inside Chat B's `e7432f5` "feat(qt-squeeze)" commit despite scope
  discipline on both sides. The rest of Chat A's files stayed as WIP, giving
  a false "committed" report to the user. Documented at
  `~/.claude/rules/common/parallel-chat-isolation.md`.

## Wave 1 Chrome results (2026-04-17)

Ran the 5-task prompt. Two green, three blocked or closed.

| Task | Result |
|---|---|
| 1 Trigger data-refresh GHA | Run #7 on commit 295d042 kicked off, status In progress at screenshot. URL: https://github.com/m6bernha/cpu-analytics/actions/runs/24574585197 |
| 2 Branch protection for main | First attempt blocked. CI workflow landed `12cbb46`. **RE-RUN GREEN** same session, classic rule saved, required check `Frontend (tsc + build)`. Backend pytest job is NOT currently required (gap, see below). |
| 3 Vercel Skew Protection | Blocked. Pro-plan feature. Hobby shows Pro badge + Upgrade button, no toggle. See strategic decision below. |
| 4 Render health check | Only `/api/health` path visible in UI. Timeout and interval not exposed. Configurable via render.yaml or Render API if needed, currently both on platform defaults. |
| 5 UptimeRobot monitor | HTTP/S, 5-minute interval, currently Up 16h15m. Historical 405 incident Apr 15 14:27 duration 1d5h (resolved by G3 HEAD-compatible health endpoint, commit `40ff320`). Ruled out as the source of "/api/health every ~5s" anomaly. |

### Branch protection gap

The saved rule requires only `Frontend (tsc + build)`. The backend pytest job
is running in CI but is not enforced as a required check. To close this:
re-open Settings -> Branches -> Edit rule for main, search the status-check
picker for the backend job name (probably "Backend (pytest)" or similar
depending on how `ci.yml` names the job), and add it. Requires a sudo-mode
re-auth same as last time.

### Follow-up decisions from Chrome run

- **Vercel Pro upgrade**: $20/mo/seat unlocks Skew Protection and build-time minutes.
  Skip recommendation: low traffic hobby project, infrequent deploys (~1 per session),
  Skew Protection protects against in-flight requests during deploy window which is a
  minor edge. Revisit if the site picks up traction.
- **/api/health flood investigator**: UptimeRobot ruled out. Most likely Render's
  internal health prober. Not an actionable problem. Close Issue 2 unless Render
  access logs show a non-Render source IP.
- **Render health check timing**: platform defaults in use. If cold-start recovery is
  ever a problem, add `healthCheckTimeout: 10` and `healthCheckInterval: 30` to
  render.yaml. Not needed today.

## New P1 issues surfaced this session

### Goodlift column missing from local parquet (Issue 16)

Chat C reported: `/api/lifter/history` returns 503 because the SQL selects
`Goodlift` but the locally preprocessed parquet was generated before the
Dots -> Goodlift rename. Production may or may not show this depending on
which parquet Render has downloaded from the data-latest release. Fixes:
1. Re-run `python data/preprocess.py` locally to regenerate the parquet
   with the Goodlift column.
2. Self-heal: extend the lifespan warmup's corrupt-parquet check to detect
   missing expected columns and force re-download, not just row-count zero.

Files: `data/preprocess.py`, `backend/app/data_loader.py`.

### CI workflow never landed (Issue 8 reopened)

The UX chat reported shipping `.github/workflows/ci.yml` but it does not
exist on local main. Only `keepalive.yml` and `refresh-data.yml` are in
`.github/workflows/`. This means:
- No regression guard on the 4 unpushed commits or the upcoming WIP commit.
- The branch-protection rule in the Chrome Wave 1 task will have nothing
  to require.

Fix: separate focused chat to write ci.yml. Not urgent enough to block the
live-site hotfix, but should land within the next 2-3 commits.

Files: `.github/workflows/ci.yml` (new).

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
