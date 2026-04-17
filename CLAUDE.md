# CLAUDE.md — Project guide for cpu-analytics

This file is for Claude Code sessions. Read it at the start of any session
in this repo, then read `NEXT_STEPS.md` for the current backlog.

## What this is

A public web app for Canadian raw powerlifters competing in CPU and IPF-sanctioned meets. Three tabs:

1. **Progression** — cohort average total change over time, filterable.
2. **QT Squeeze** — four-block Open-only view of CPU qualifying total coverage across pre-2025 / 2025 / 2027 standards.
3. **Lifter Lookup** — name search with history plot against QT reference lines, plus manual entry for hypothetical trajectories.

Data source: OpenPowerlifting OpenIPF bulk export, refreshed weekly.

## Live URLs

- Frontend: https://cpu-analytics.vercel.app
- Backend: https://cpu-analytics-backend.onrender.com
- Repo: https://github.com/m6bernha/cpu-analytics

## Stack

- **Backend:** FastAPI + DuckDB over Parquet, Python 3.11+ (prod runs 3.12 via Docker).
- **Frontend:** Vite + React 19 + TypeScript + TanStack Query + Recharts + Tailwind v3.
- **Data pipeline:** GitHub Actions workflow (Sundays 06:13 UTC) downloads openipf-latest.zip, runs `data/preprocess.py`, publishes parquet to a rolling `data-latest` GitHub Release.
- **Backend hosting:** Render.com free tier (`render.yaml`). 15-min idle spindown, ~20-50 s cold start.
- **Frontend hosting:** Vercel Hobby tier (`frontend/vercel.json`), auto-deploys on push to `main`.
- **Fly.io config (`fly.toml`) exists but is NOT deployed.** Ignore unless asked to migrate.

## Local development

```bash
# One-time
cd cpu-analytics
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -r backend/requirements.txt

# Preprocess (requires sibling openipf-2025-11-08/ directory with the CSV)
python data/preprocess.py

# Frontend
cd frontend && npm install

# Run backend
.venv/Scripts/activate
uvicorn backend.app.main:app --reload

# Run frontend (in another terminal)
cd cpu-analytics/frontend && npm run dev
```

Frontend talks to `VITE_API_BASE` (defaults to `http://127.0.0.1:8000`).

## Pre-push checklist

- `cd frontend && npm run build` — catches TypeScript strict errors that will blow up the Vercel build. Skipping this and pushing is how we broke the first frontend deploy attempt.
- No need to run the backend's test suite because there isn't one (yet).

## URL state conventions

Every user-facing, shareable view is encoded in `window.location.search` via the
`useUrlState` hook in `frontend/src/lib/useUrlState.ts`. Keys are omitted from
the URL when they equal their default, so a pristine page has a clean URL.

Supported URL keys (as of 2026-04):

| Key | Scope | Example values |
|---|---|---|
| `tab` | App shell | `progression`, `qt`, `lookup` |
| `sex`, `weight_class`, `equipment`, `tested`, `event`, `division`, `age_category`, `x_axis` | Progression filters | `M`, `83`, `Raw`, `Yes`, `SBD`, `Open`, `All`, `Years` |
| `mode` | Lifter Lookup | `search`, `compare`, `manual` |
| `lifter` | Lifter Lookup search mode | `Matthias Bernhard` |
| `lifters` | Lifter Lookup compare mode | `Matthias Bernhard,Alex Mardell` (up to 4) |

Example deep links:
- `?tab=progression&weight_class=83&x_axis=Months`
- `?tab=lookup&lifter=Matthias%20Bernhard`
- `?tab=lookup&mode=compare&lifters=Matthias%20Bernhard,Alex%20Mardell`

When adding a new component with URL-backed state, register only the keys it
owns. Multiple `useUrlState` instances coexist safely on the same page — each
only touches its own keys.

## Event type handling (lifter lookup)

OpenIPF's `Event` column has seven values: `SBD`, `BD`, `SD`, `SB`, `S`, `B`,
`D`. Only `SBD` (full power) gives a total that's comparable across meets.
Other events produce a `TotalKg` that's the partial sum (just bench, or
bench+deadlift, etc.), and plotting them on the same y-axis is misleading.

The lifter-lookup single-lifter chart and the compare chart both filter to
`Event === 'SBD'`. Non-SBD meets still appear in the meet table below the
chart, visually muted, with the event type in a color-coded chip and a
hover tooltip spelling out the full name (see `EVENT_DESCRIPTION`). The
Δ-first column in the table is computed against the first SBD meet
specifically, not the first meet of any kind.

## Known gotchas

- **Recharts v3.8 strict types.** `Tooltip` formatter/labelFormatter callbacks receive `ValueType | undefined` and `ReactNode` for label. Do not annotate params as `number` / `string`. See `cpu-analytics/frontend/src/tabs/*.tsx` for the pattern.
- **Render cold start.** First request after 15 min idle takes up to ~50 s. UptimeRobot (free) pinging `/api/health` every 5 min keeps it warm.
- **Vercel auto-detects the repo as a multi-service project** because both `frontend/` and `backend/` are present. On new project import, set **Root Directory = `frontend`** to force single-service Vite mode. `vercel.json` lives inside `frontend/`, not at repo root.
- **Tested filter has one value.** The OpenIPF export is IPF-only, every row is `Tested=Yes`. The filter dropdown should be hidden or replaced with a static note.
- **Age column is ~70% NULL.** Any age_category filter silently drops many rows. The Progression tab shows a hint about this.
- **Division is free-text.** `Division='Open'` works for CPU specifically, verified empirically (see `backend/app/qt.py` comments). Not federation-portable.
- **Weight class canonicalization** collapses historical 1-kg-off variants into modern IPF classes. See `backend/app/weight_class.py`. Fine in aggregate, wrong at the individual level for some edge cases.
- **TanStack Query caching**: every query that feels "static" (filters, qt-blocks, qt-standards) uses `staleTime: 10 * 60 * 1000` with `retry: 3`, not `staleTime: Infinity`. Infinity caches bad cold-start responses forever — the empty-equipment regression taught us this. The `fetchFilters` fetcher additionally validates that required arrays are non-empty and throws on partial data, so retry kicks in for partial responses too.
- **FastAPI startup warms DuckDB.** `backend/app/main.py` registers a `lifespan` handler that runs `SELECT COUNT(*)` against both views at app start. This forces parquet reads into the boot window rather than the first user request. If you add a new parquet or new view, extend the warmup to touch it.
- **Chart legends at top, not bottom.** Recharts defaults the legend to `verticalAlign='bottom'`, which overlaps the x-axis label. Every chart in this app uses `<Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />`. Keep this convention on new charts.
- **PR detection is per-Event.** `lifters.py` marks `is_pr=True` if the meet's TotalKg exceeds all prior meets of the same Event type (SBD vs B vs BD etc). This prevents bench-only PRs from being compared against full-power totals.
- **Comeback filter (max_gap_months).** Progression endpoint accepts an optional `max_gap_months` int param. When set, lifters with any inter-meet gap exceeding that threshold are excluded from the cohort before aggregation. The frontend exposes this as a dropdown (Off/6/12/18/24/36).
- **Std dev band on Progression chart.** Uses Recharts `Area` with `dataKey="stdBand"` (a [y-std, y+std] tuple per point). The backend computes `std` per x-bucket alongside `mean`. The chart uses `ComposedChart` (not `LineChart`) to support both Area and Line.
- **Weighted OLS trendline.** polyfit with `w=sqrt(lifter_count)`. Dense early-year buckets dominate the slope. Weighted R-squared reflects this. The old unweighted fit gave equal influence to 15-lifter tail buckets and 2,700-lifter year-0 buckets.
- **Rate of improvement = regression slope.** `lifters.py` runs `np.polyfit(days, totals, 1)` across all SBD meets, not just first-to-last. More honest for non-monotonic careers.
- **53 kg men dropped.** `weight_class.py` returns NaN for men below 58 kg. No QT standard exists. Extremely rare in CPU.
- **Survivorship stats.** Progression endpoint returns `n_all_lifters` (including 1-meet) and `avg_first_total` so the frontend shows retention rate and day-0 population context.
- **Search metadata shows LATEST meet.** The `search_lifters` SQL sorts Date DESC so rn=1 is the most recent meet. LatestEquipment, LatestWeightClass, LatestMeetDate are now actually latest.
- **Percentile scope MUST match cohort.** `_compute_percentile` now uses a `self_best` CTE scoped to the same sex/class/equipment/country/IPF/SBD filters as the `bests` CTE. The earlier bug selected the lifter's global SBD max, which would rank out-of-scope totals against an in-scope cohort.
- **DuckDB cursor per request.** `data.py` exposes `get_cursor()` and `with_cursor()` (context manager). The base connection holds the `:memory:` DB and parquet views; every request handler gets its own cursor. DuckDB's parent connection is not safe for concurrent `execute()` calls. `get_conn()` is a deprecated alias. `qt.py` helpers (`_load_scope`, `_load_qt_standards`, `_load_best_totals_per_era`) take the cursor as first arg so a single cursor covers the whole computation.
- **QT blocks always returns 4 keys** (`M_Nationals`, `M_Regionals`, `F_Nationals`, `F_Regionals`), even when `groupby` yields none for a combo. Backend initializes the dict with empty lists before iterating.
- **TotalKg can be null** in LifterMeet. DQ / bombed / bench-only meets may have null totals. Frontend guards with `!= null` before arithmetic; backend `_safe_best` returns None on empty.
- **Per-lift cohort progression** requires all three lift columns non-null, so this view is SBD-only in practice. A bench-only meet row cannot contribute because the SQL's `WHERE Best3SquatKg IS NOT NULL AND Best3BenchKg IS NOT NULL AND Best3DeadliftKg IS NOT NULL` excludes it. For individual lifter per-lift view, partial events DO contribute to whichever lift(s) they provide, because the frontend renders each lift as an independent Line with `connectNulls`.
- **Projection date math uses UTC.** `new Date(iso)` + `setDate()` drifts across DST. All date arithmetic uses `Date.UTC` to match the `fmtDate` ISO-parse convention elsewhere.
- **useUrlState collision guard** warns in dev if two components register the same URL key. Components must own DISJOINT key sets. Uses ref-counted Map (not Set) so StrictMode double-mount in dev doesn't false-positive.
- **ErrorBoundary wraps each tab.** A render-phase crash in one tab shows a recoverable error panel with a "Try again" button, while the other tabs remain usable.
- **Manual trajectory is hardened.** entries list capped at 200, kg fields capped at 2000, dates restricted to 1960 through next year, sex must match ^[MF]$, all string fields have max_length. Protects the public POST endpoint from DoS.
- **Search wildcards are escaped.** `q.replace('%', '\\%')` + `ESCAPE '\\'` on the LIKE clause. Query term capped at 50 chars. A search of `%%%%%` cannot force a full-table scan.
- **Data loader uses unique temp files.** `tempfile.NamedTemporaryFile` prevents concurrent cold-start downloads from stomping each other's partial writes.
- **Corrupt-parquet self-heal.** Lifespan warmup deletes local parquet files if any view comes back 0-rows, so the next cold-start re-downloads rather than serving broken data indefinitely.
- **accessibility:** nav has `role="tablist"` with `aria-selected`; search inputs have `aria-label`.
- **Parquet is Canada + IPF scoped at preprocess time.** `data/preprocess.py` applies `Country=='Canada' & ParentFederation=='IPF'` before writing the parquet. The app never serves anything outside that scope (see `scope.py`). This shrinks the parquet ~15-20x vs. publishing the full OpenIPF export. The Canada+IPF pool is ~5,400 lifters.
- **QT coverage aggregates in SQL.** `qt._load_best_totals_per_era` does `GROUP BY Sex, WeightClass, Name` with `MAX(CASE WHEN Date < <cutoff> THEN TotalKg END)` columns per era + 24-month window. compute_coverage reads that small frame and does only the QT-threshold comparison in pandas. Do not regress to pulling the full scope into pandas.
- **`compute_blocks` and `get_filters` are lru_cached.** Results only change on parquet refresh (which triggers a container restart). maxsize is small (1-8); every new cache entry costs memory.
- **`/api/health` accepts GET and HEAD.** UptimeRobot free plan is HEAD-only. Use `@app.api_route(methods=["GET", "HEAD"])` for any new probe-style endpoint.
- **`/api/ready` is a real readiness probe.** Runs `SELECT 1` via `get_cursor()`. Returns 503 if the parquet views are broken. `/api/health` is liveness only and doesn't touch DuckDB.
- **Request timing middleware** logs `[req] METHOD /path STATUS <ms>` on every request. Crashes log `CRASH in <ms>ms`. Visible in Render logs.
- **Dedicated DuckDB exception handler** catches `duckdb.Error`, logs the request path + exception + stack trace, returns a clean 503 JSON `{"error": "database_error"}`. Means future DuckDB issues show which endpoint triggered them.
- **QueryClient defaults** (main.tsx): `retry: 3`, exponential backoff up to 30 s, `staleTime: 5 min`, `refetchOnWindowFocus: false`. Tuned for the Render free-tier cold start. Individual queries override staleTime where appropriate.
- **Frontend error display pattern.** Every query uses `lib/QueryStatus.tsx`: `QueryErrorCard` (with HTTP status + Retry button + cold-start explanation) on `isError`, `LoadingSkeleton` on `isLoading`. Keeps users informed instead of rendering partially.
- **CompareView is lazy-loaded.** `const CompareView = lazy(() => import('./CompareView'))` in `LifterLookup.tsx`. Ships as its own ~8 KB chunk. Do NOT add a static import from CompareView back into LifterLookup - it will defeat the split (vite warns `INEFFECTIVE_DYNAMIC_IMPORT`).

## Pre-push checklist

- `cd frontend && npm run build` -- catches TypeScript strict errors.
- `cd cpu-analytics && .venv/Scripts/python -m pytest backend/tests/ -v` -- 25 tests covering progression (age category baseline, division filter, edge cases) and lifter search/history (search, PR detection, event types).

## Scope

Backend defaults enforce Country=Canada, ParentFederation=IPF (see `backend/app/scope.py`). Widening is a one-line change. Do not remove the defaults silently — the entire product framing is CPU/IPF.

## Data pipeline invariants

- `data/preprocess.py` writes `openipf.parquet` + `qt_standards.parquet` to `data/processed/` (gitignored).
- Production containers download these two files from the `data-latest` GitHub Release on first request (`backend/app/data_loader.py`).
- `data/qualifying_totals_canpl.csv` is vendored into git (32 rows, hand-curated). CI needs it available without the 285 MB OpenIPF CSV.

## User preferences (Matthias)

- **Beginner to everything.** No prior Python, React, FastAPI, Docker, or deploy experience. Explain concepts, not just commands. See `~/.claude/projects/<this-project>/memory/user_profile.md` for the longer note.
- **Spartan writing style.** No em dashes, no semicolons, no rhetorical questions. Applies to both responses and UI strings.
- **Automate aggressively.** Default to action. Only prompt for manual steps that genuinely need human hands (auth, dashboards, account creation).

## Deploy behaviour

- Push to `main` → Vercel deploys the frontend automatically.
- Push to `main` → Render redeploys the backend automatically.
- Data refresh is a separate weekly GitHub Actions cron.

## Roadmap

The full 9-phase implementation roadmap lives at `~/.claude/plans/gleaming-toasting-lightning.md`.

**Phases 0-6 + roundtable review shipped (2026-04-15/16):**
- Phase 0: Five frontend bug fixes
- Phase 1: Critical age_category baseline fix + 25 pytest tests
- Phase 2: Mobile polish (QT column hiding, back button, date axis, touch dots, tab persistence)
- Phase 3: Division from API, CompareView perf fix, Dots column
- Phase 4: R-squared, std dev band, age data loss indicator, survivorship note
- Phase 5: Comeback lifter gap detection (max_gap_months filter)
- Phase 6: Per-lifter metrics (QT proximity, rate of improvement, PR detection, lift ratios)
- Roundtable: weighted OLS, search metadata fix, survivorship stats, regression-based rate, 53kg drop, name disclaimer

**Phases 7-9 shipped (2026-04-16):**
- Phase 7: Weight class migration (class change chips, same_class_only toggle)
- Phase 8: Prediction (individual projection, cohort projection with widening CI, percentile rank)
- Phase 9: Per-lift (Squat / Bench / Deadlift) curves for cohort + individual lifter

**Reliability overhaul shipped (2026-04-16, G1-G5):**
- G1: Per-request DuckDB cursors fix concurrency crashes
- G2: Parquet filtered to Canada+IPF at preprocess + SQL aggregation + caching
- G3: /api/health accepts GET+HEAD, /api/ready probe added
- G4: Error cards with Retry, loading skeletons, QueryClient retry defaults
- G5: GHA keepalive, request timing middleware, DuckDB exception handler

**Tab taxonomy + attribution (2026-04-16):**
- Tab order: Progression, Athlete Projection (BETA), Lifter Lookup, QT Squeeze
- Attribution footer with LinkedIn/Instagram on every page
- Equipment collapsed to Raw/Equipped; Event to Full Power/Bench Only
- Division uses CPU canonical labels with backend alias-mapping
- Age Category (Numeric) dropdown retired (merged into Division)
- Dots renamed to Goodlift (GLP) through the pipeline
- Lifter Lookup modes are pill-nav instead of overflow-scroll
- Reference line labels repositioned to prevent cut-off

**See NEXT_STEPS.md for the living backlog.** Key P0 action: trigger the
weekly data-refresh GHA manually so the Canada+IPF-filtered parquet
actually reaches production.

**Audit rounds (2026-04-16):**
- Round 1: 10 bugs fixed (percentile scope, NaN%, QT block keys, null TotalKg,
  DuckDB thread safety via cursor(), stale copy)
- Round 2: 8 hardening fixes (manual DoS guards, LIKE escaping, data_loader
  temp file race, Math.min spread antipattern, useUrlState ref-counting,
  corrupt-parquet recovery, ErrorBoundary, aria-labels)
- Round 3: 5 interaction fixes (per-lift filter plumbing amber warning,
  manual response shape completeness, empty-response helper, preprocess
  fail-hard on missing columns, vectorized canonical_weight_class)

**Production reliability overhaul (2026-04-16, G1-G5):**
- G1: Per-request DuckDB cursors eliminate "No open result set" concurrency
  crashes. New `get_cursor()` and `with_cursor()`. 4 regression tests with
  32 parallel threads.
- G2: Parquet filtered to Canada+IPF at preprocess (15-20x shrink). QT
  coverage aggregates in SQL. `compute_blocks` and `get_filters` cached.
  psutil RSS logged at startup.
- G3: `/api/health` accepts HEAD (fixes UptimeRobot). New `/api/ready`
  readiness probe.
- G4: Frontend error cards + retry + skeletons + QueryClient retry/backoff
  defaults.
- G5: GitHub keepalive cron, request timing middleware, DuckDB exception
  handler.
- Plus CompareView lazy-loaded as its own 8 KB chunk.

**77 tests passing** across progression, lifters, projection, qt, manual,
security, weight_class, and concurrency modules.

## When extending this

- New API endpoint: add to `backend/app/main.py`, wire a module in `backend/app/`, add a typed fetcher in `frontend/src/lib/api.ts`.
- New tab: add a component in `frontend/src/tabs/`, register in `frontend/src/App.tsx`'s `TABS` array and switch. If the tab has shareable state, use `useUrlState`.
- New filter: add the enum in `backend/app/filters.py` if it's enumerable, and a `<Select>` in `Progression.tsx` (or wherever it applies).
- New chart: use a dark-theme palette anchored on `#569cd6` (blue), `#ce9178` (orange), `#4ec9b0` (teal), `#c586c0` (purple). `Legend` verticalAlign top. `CartesianGrid` stroke `#3f3f46`.

## Responsive conventions

The app stacks vertically below the `md` Tailwind breakpoint (768 px):
- App header: title + nav stack on small screens. Nav is `overflow-x-auto` so
  extra tabs scroll horizontally rather than wrap.
- Progression tab: filter aside drops below the chart on narrow screens via
  `flex flex-col md:flex-row`.
- Lifter Lookup: search/detail already uses `grid grid-cols-1 lg:grid-cols-3`.
- QT Squeeze: each block is `grid grid-cols-1 lg:grid-cols-5` (2-col table +
  3-col chart); wide tables wrap in `overflow-x-auto`.

Charts use `ResponsiveContainer` with fixed pixel heights (`h-[400px]` or
`h-[480px]`). Width auto-scales. Keep chart heights the same on mobile so the
aspect ratio stays readable on phones.

## Open action items (deferred work)

See `NEXT_STEPS.md` at the repo root for the prioritized backlog. Highest-impact
items summarized here:

### Manual action for the user (immediate)

- **Trigger the data-refresh GHA manually** at
  https://github.com/m6bernha/cpu-analytics/actions to activate the Canada+IPF
  parquet shrink in production. Until the next Sunday 06:13 UTC cron, Render
  is still downloading the pre-shrink parquet on cold start.

### High-priority code work

1. **Lazy-load `LifterDetail`** to claim the remaining ~200 KB Recharts saving.
   The CompareView split only yielded 8 KB because LifterDetail imports Recharts
   statically from the main bundle. Wrap LifterDetail the same way CompareView
   is wrapped.
2. **Per-lift filter plumbing.** Frontend shows an amber warning that per-lift
   view ignores age_category, same_class_only, and max_gap_months. Data-correctness
   gap. Extend `compute_lift_progression` to accept and apply those filters
   (including baseline recomputation for age_category).

### Medium-priority features

3. **Bodyweight + Dots progression curves.** Already in the parquet, shown in
   the meet table, never plotted. Copy the progression pattern to plot Dots/BW
   over time.
4. **Coach view**: "Am I on pace for Nationals 2027?" Given a target date and
   the already-built individual projection, compute expected total on that date
   and the gap to the QT.
5. **Monitor RSS after next cold start.** Look at Render logs for the
   `[startup] process RSS: <MB>` line to quantify the G2 memory improvement.

### Low-priority / polish

6. **Hypothesis property-based tests** for `canonical_weight_class`.
7. **Extract LifterDetail to its own file** for easier lazy-loading.
8. **UptimeRobot dashboard verification** once HEAD is live (pending user
   manual navigation since the Chrome extension blocks dashboard domains).
