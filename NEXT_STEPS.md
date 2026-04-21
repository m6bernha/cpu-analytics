# Next Steps

Living backlog for the cpu-analytics project. Captured 2026-04-16 during the
Batch 1-3 feedback session. When starting a new Claude session, read this
file after `CLAUDE.md`. Cross items off as they land; add new ones as they
arise.

Ordering is a judgment call between impact and effort.

---

## Session plan -- 2026-04-20 (laptop campus study day) -- ALL SHIPPED

Four parallel worktree chats on laptop, all merged to main on desktop
the same day:

1. **Compare chart summary cards + QT reference lines** (P1) -- SHIPPED
   `0e9f0ba`. Per-lifter cards (best total, rate kg/month, meet count,
   first-meet date, class migrations, QT status) + optional QT reference
   line set. Single-file scope in CompareView.tsx.
2. **Bodyweight + GLP cohort progression curves** (P2) -- SHIPPED
   `fca221e`. Metric selector (TotalKg / Bodyweight / Goodlift) via the
   existing compute_progression pattern. Adds 9 pytests (165 -> 174).
3. **useUrlState key collision Vitest** (P5) -- SHIPPED `84a7ea7`.
   Vitest wired from scratch (vitest + @testing-library + jsdom).
   3/3 passing. Also `e2b9d5f` excludes `e2e/**` from Vitest discovery
   so Playwright tests don't run in jsdom.
4. **Playwright E2E smoke test scaffold** (P5) -- SHIPPED `454f1de`.
   Chromium config + 6 smoke tests. `npm run test:e2e` local only.
   Needs `npx playwright install chromium` on first run. NOT wired into
   CI yet (strategic decision deferred).

### Gated items NOT touched this session

User decision or manual browser action required before these can start:

- Issue 1 Recharts display:none warnings: shell fix vs per-chart guard.
- Issue 12 Render cold-start strategy: keep free+keepalive / Hobby $7 /
  Fly Machines migration.
- G4 per-chart Recharts guard: blocks on Issue 1.
- G5 disclaimer copy pass: blocks on everything else, touches every tab
  file.
- Branch protection for backend pytest: user manual via Chrome, needs
  sudo re-auth.
- P0 data-refresh Run #7 green verification: user manual.

### Athlete Projection / P3 weighting methodology -- BACKBURNER

Matthias parked this on 2026-04-21 pending direct consultation with
statistics professors to ensure the methodology is academically sound
before any projection numbers ship to production. The four candidate
methodologies (A pure personal / B pure cohort / C Bayesian shrinkage /
D mixed-effects) remain documented in the P3 section below, but no
implementation work should happen on the Athlete Projection tab until
he returns with an academic-grounded decision.

The Coach "on pace for Nationals 2027" widget (P2) does NOT require the
P3 decision and can ship independently using the existing linear
individual projection math.

---

## P0 -- Live site monitoring

### Data refresh workflow -- VERIFIED HEALTHY 2026-04-21

Latest Run #7 (manually triggered) completed Success in 39 s total
(refresh job 35 s), Release step uploaded data-latest successfully.
One non-blocking Node 20 deprecation annotation, no failures.

Live site `https://cpu-analytics.vercel.app/?tab=progression` hydrates
cleanly. Progression chart renders with mean change line, +-1 SD band,
and dashed trendline. Filter fetches succeed (sex M->F repopulates
female weight classes, selecting a class refreshes the cohort). No
"Filter load failed: age_category" banner present.

Weekly cron fires Sundays 06:13 UTC. If a future run fails, trigger
manually:

1. Go to https://github.com/m6bernha/cpu-analytics/actions
2. Open "Refresh OpenIPF data"
3. Click "Run workflow" -> "Run workflow"
4. Wait ~3 minutes
5. Either restart Render manually or wait for next spin-down/up cycle

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

### LifterDetail Recharts static import defeats the CompareView split — SHIPPED

G3 LifterDetail lazy-load landed 2026-04-20. `LifterDetail` + its helpers
(ClassChangeBadge, formatters, findQtForLifter, event/era metadata) extracted
to new `frontend/src/tabs/LifterDetail.tsx` and lazy-imported from
`LifterLookup.tsx`. Both usages (search-mode and inside ManualEntryForm)
wrapped in Suspense with LoadingSkeleton fallback.

**Bundle before:** `index.js` ~663 KB (Recharts bundled into main).
**Bundle after:** `index.js` 295.61 KB (-55%), CartesianChart 357.19 KB lazy,
LifterDetail 18.11 KB lazy, CompareView 11.18 KB lazy.

Files: `frontend/src/tabs/LifterLookup.tsx` (-700 lines),
`frontend/src/tabs/LifterDetail.tsx` (new, 679 lines).

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
isolation. On main at `a6dc701`.

### Compare chart data gaps -- SHIPPED

Commit `0e9f0ba` landed 2026-04-20. Per-lifter summary cards above the
chart (best total, rate kg/month, meet count, first-meet date, class
migrations, QT status) plus optional QT reference line set chosen by the
user. Single-file scope in `frontend/src/tabs/CompareView.tsx`. Bundle
went from 11.18 KB to 16.00 KB as expected.

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

### Coach "on pace for Nationals 2027" widget

Fills the Athlete Projection BETA placeholder with one useful widget that
does NOT need the P3 weighting decision to ship.

Inputs: lifter (search) or current manual entry, target date (default
next Nationals), target QT (Regionals 2025/2027, Nationals 2025/2027,
custom).

Output: predicted total using the existing individual linear projection,
kg gap to selected QT, on-pace badge with honest-brokerage disclaimer.

Depends on nothing new. Reuses projection math in
`backend/app/projection.py`. UI-only change in the BETA tab file.

Does NOT replace the full Athlete Projection spec above (which still
needs P3 for the blended personal+cohort math). Ships independently as
a useful-while-you-wait widget.

Estimated effort: 1 focused session.

Files: `frontend/src/tabs/AthleteProjection.tsx` (fill placeholder),
possibly a small helper in `backend/app/projection.py` if kg-gap needs
server-side QT lookup.

---

## P3 -- Projection weighting roundtable (BACKBURNER pending stats consult)

**Status 2026-04-21**: Matthias has parked this item pending direct
consultation with statistics professors. The four methodologies below
remain documented for reference. No implementation work on the Athlete
Projection tab math should happen until an academically grounded
decision lands. The Coach "on pace for Nationals 2027" widget (P2) is
the correct path to fill the Athlete Projection BETA placeholder in
the meantime because it reuses the existing linear projection without
requiring this decision.

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

### More tests for compute_lift_progression — SHIPPED

8 new tests in `backend/tests/test_progression.py`
TestLiftProgressionFilters cover per-lift plumbing of age_category,
max_gap_months, same_class_only. P5 remainder shipped 2026-04-20 in
commit `e3230a0`: Equipment=Equipped aggregation test + Division=Master 1
alias-matching test. 165/165 backend tests passing.

### useUrlState key collision regression test -- SHIPPED

Commit `84a7ea7` landed 2026-04-20. Vitest wired from scratch
(`vitest`, `@testing-library/react`, `@testing-library/jest-dom`,
`jsdom`). Three tests in `frontend/src/lib/useUrlState.test.tsx`:
overlapping keys fire the warning, disjoint keys do not fire, ref
count survives unmount. 3/3 passing. `npm run test` runs via Vitest.
`e2b9d5f` follow-up excludes `e2e/**` from Vitest discovery.

### End-to-end smoke test -- SHIPPED (local only, not in CI)

Commit `454f1de` landed 2026-04-20. Playwright chromium scaffold with
six smoke tests in `frontend/e2e/smoke.spec.ts`. Covers `/`, `/?tab=qt`,
`/?tab=lookup`, search flow, compare deep link, manual entry submit.
Runnable via `npm run test:e2e` locally after
`npx playwright install chromium`. NOT wired into CI -- strategic
decision deferred because GHA runners need the browser binary download
on every run (~30 s cold start tax per CI run, weighed against the
~6 smoke tests it catches). Revisit if the frontend sprouts a flaky
interaction the unit tests miss.

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
| 1 | Recharts -1x-1 warnings from display:none inactive tabs in App.tsx | high | L per-chart | G4 parallel chat | DECIDED 2026-04-21: per-chart guard (Option B). In-flight on branch `work/g4-chart-guard`. | in progress |
| 2 | /api/health hit every ~5s from one IP | low | S | none (ruled out UptimeRobot) | none | UptimeRobot verified 5min interval, likely Render internal health prober, no action needed unless logs confirm rogue source |
| 3 | Double request logging (timing middleware + uvicorn access log) | medium | S | G1 backend-perf | closed | SHIPPED `1f0b62e` — /api/health suppressed in timing middleware, uvicorn access log retained |
| 4 | No Cache-Control or ETag on weekly-stable JSON endpoints | high | S-M | G1 backend-perf | closed | SHIPPED `1f0b62e` — ETag W/"parquet-<mtime>" + Cache-Control public, max-age=300 on filters, qt/standards, qt/blocks. 304 verified on If-None-Match |
| 5 | No gzip middleware on backend responses | high | S | G1 backend-perf | closed | SHIPPED `1f0b62e` — GZipMiddleware(minimum_size=500), Content-Encoding: gzip verified on qt/blocks |
| 6 | /assets/* hashed bundles served with max-age=0 | high | S | CI-redispatch chat | closed | SHIPPED `12cbb46` — vercel.json headers rule: Cache-Control public, max-age=31536000, immutable |
| 7 | Stale Fly.io references in refresh-data.yml + qt.py comments | polish | S | CI-redispatch chat + G2 data_loader sweep | closed | SHIPPED `12cbb46` (refresh-data.yml) + `51ca6b0` (data_loader.py; qt.py was already clean) |
| 8 | No CI build gate (tsc + build + pytest) on PR/push | blocker | M | CI-redispatch chat | closed | SHIPPED `12cbb46` — .github/workflows/ci.yml with Frontend (tsc + build) and backend pytest jobs, triggers on push + PR to main |
| 9 | refresh-data.yml missing pip cache (~25s/run) | polish | S | CI-redispatch chat | closed | SHIPPED `12cbb46` — setup-python with cache: pip |
| 10 | Deprecated action versions (Node 20 EOL warnings) | polish | S | CI-redispatch chat | closed | SHIPPED `12cbb46` — checkout v4→v6, setup-python v5→v6, action-gh-release v2→v3 |
| 11 | Vercel Skew Protection not enabled | low | strategic | decision | Pro-plan feature ($20/mo), Hobby cannot toggle | PARKED, low traffic hobby project, Pro upgrade not justified |
| 12 | Render free-tier cold start still user-visible (~50s) | medium | L | strategic | DECIDED 2026-04-21: stay on Option A (free + keepalive). Fly Machines free tier requires a credit card Matthias declined to add. Upgrade path is Render Hobby $7/mo if keepalive ever misses or a user complains. | closed (decision) |
| 13 | Verify data.py per-request cursor fix landed cleanly | polish | S read | UX chat | none | verified, no commit needed |
| 14 | LifterLookup.tsx ~44KB, more code-splitting possible | polish | M | G3 LifterDetail lazy-load | closed | SHIPPED 2026-04-20 — main bundle 663→295 KB (-55%); LifterDetail extracted to own file + lazy-loaded |
| 15 | backend/requirements.txt pin discipline check | polish | S | UX chat | none | verified, no commit needed |
| 16 | Local parquet lacks Goodlift column, 503 on /api/lifter/history | high | S | G2 data_loader sweep | closed | SHIPPED `51ca6b0` — assert_parquet_health() in data_loader.py self-heals on both zero-row AND missing-column |
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
2. **G2 data_loader hardening + Fly.io sweep — SHIPPED 2026-04-20**
   (commit `51ca6b0`). Scope deviations from original prompt: the stale
   Fly.io reference was in `backend/app/data_loader.py:4`, not
   `backend/app/qt.py`; and the chat added a new `assert_parquet_health()`
   function rather than touching `main.py` lifespan (out of scope). Covers
   both zero-row and missing-column parquet in one place. Closes Issue 7
   remainder + Issue 16.
3. **G3 LifterDetail lazy-load — SHIPPED 2026-04-20.** Files:
   `frontend/src/tabs/LifterLookup.tsx` split, new `LifterDetail.tsx`.
   Closed Issue 14 and the pre-existing P1 "LifterDetail Recharts static
   import" item. Main bundle 663 KB → 295.61 KB.
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

## Wave 2 UX polish (2026-04-17 evening)

Two small UX fixes shipped in a single commit, plus the fallout:

### SHIPPED `24dadb5`: meet-table no-scroll + class-change tooltip

- Dropped `overflow-x-auto` from the LifterDetail meet table wrapper.
- Removed `whitespace-nowrap` from the Sq/Bn/Dl value cell and Sq/Bn/Dl %
  cell so triplets wrap vertically inside their column when space is tight.
- Kept nowrap on Date, Event chip, Class (short values, safe to stay).
- Replaced the native `title=` attribute on the amber class-change badge
  with a portal-rendered tooltip ("Weight class changed from previous
  meet") so it escapes the table's stacking context.

Verified live on cpu-analytics.vercel.app. Frontend CI green on the push.

### NEW P1: Backend pytest CI broken since the workflow landed

CI job "Backend (pytest)" fails with
`ModuleNotFoundError: No module named 'backend'` on every run. Not a
regression from 24dadb5, pre-existing since the ci.yml landed in `12cbb46`.

**Root cause**: `.github/workflows/ci.yml` runs `pytest backend/tests/`.
The plain `pytest` shell entrypoint does NOT prepend cwd to `sys.path`,
so `from backend.app import ...` imports in the tests fail. The fix is
`python -m pytest backend/tests/` (python prepends cwd).

Tests pass locally because `.venv/Scripts/python -m pytest ...` is what
Matthias runs. CI was using the shortcut form.

### 3rd instance of parallel-chat commit hygiene lapse

Commit `24dadb5` title says "hover tooltip on class-change triangle" but
the diff also removed `overflow-x-auto` + two `whitespace-nowrap`
classes — those were the scroll fix from a separate "chat 1" task that
never got its own commit. The chat 1 report to Matthias claimed "fix was
already verified" but never reported a SHA. The fix is in production now
but under a misleading commit message.

Also inside 24dadb5: the `ClassChangeBadge` docstring still references
`overflow-x-auto` as present tense even though the same commit removed
it. Stale comment fixed in this session.

Pattern: three times now in one day. Parallel chats against the same
worktree keep producing commits whose messages don't match their scope.
See `~/.claude/rules/common/parallel-chat-isolation.md` (unchanged, still
applies). When the next pile of parallel chats kicks off, use git
worktrees or dispatch serially.

## Wave 1 Chrome results (2026-04-17)

Ran the 5-task prompt. Two green, three blocked or closed.

| Task | Result |
|---|---|
| 1 Trigger data-refresh GHA | Run #7 on commit 295d042 kicked off, status In progress at screenshot. URL: https://github.com/m6bernha/cpu-analytics/actions/runs/24574585197 |
| 2 Branch protection for main | First attempt blocked. CI workflow landed `12cbb46`. **RE-RUN GREEN** same session, classic rule saved, required check `Frontend (tsc + build)`. Backend pytest job is NOT currently required (gap, see below). |
| 3 Vercel Skew Protection | Blocked. Pro-plan feature. Hobby shows Pro badge + Upgrade button, no toggle. See strategic decision below. |
| 4 Render health check | Only `/api/health` path visible in UI. Timeout and interval not exposed. Configurable via render.yaml or Render API if needed, currently both on platform defaults. |
| 5 UptimeRobot monitor | HTTP/S, 5-minute interval, currently Up 16h15m. Historical 405 incident Apr 15 14:27 duration 1d5h (resolved by G3 HEAD-compatible health endpoint, commit `40ff320`). Ruled out as the source of "/api/health every ~5s" anomaly. |

### Branch protection gap -- CLOSED 2026-04-21

Classic branch protection rule on `main` now requires both
`Frontend (tsc + build)` and `Backend (pytest)` status checks. Admin
bypass remains enabled ("Do not allow bypassing" left unchecked) so
admin pushes can still land WIP when explicitly needed. Verified via
Claude in Chrome session after sudo re-auth.

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

### Goodlift column missing from local parquet (Issue 16) — SHIPPED

Commit `51ca6b0` landed 2026-04-20. New `assert_parquet_health()` in
`backend/app/data_loader.py` covers both zero-row and missing-column in one
place, called from `ensure_parquets()` on cold-start. Raises HTTPException(503)
surfaced via FastAPI middleware when called per-request. Also scrubbed the
stale Fly.io reference at `backend/app/data_loader.py:4` (qt.py was already
clean, despite the original prompt's scope guess).

Remaining user step: re-run `python data/preprocess.py` locally to regenerate
the Goodlift-column parquet if the dev environment still has the stale file.
Production Render picked up the fresh parquet at next cold-start via the
data-latest release; the self-heal now catches future schema drift
automatically.

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
