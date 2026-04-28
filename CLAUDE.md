# CLAUDE.md — Project guide for cpu-analytics

This file is for Claude Code sessions. Read it at the start of any session
in this repo, then read `NEXT_STEPS.md` for the current backlog.

## What this is

A public web app for Canadian raw powerlifters competing in CPU and IPF-sanctioned meets. Four primary tabs in the nav, plus an About page accessible by direct URL while it's being finalized:

1. **Progression** — cohort average total change over time, filterable.
2. **Athlete Projection (BETA)** — per-lift Engine C Bayesian shrinkage projection stratified by age division × IPF-GL bracket, with Kaplan-Meier dropout-adjusted prediction intervals. See `backend/app/athlete_projection.py`.
3. **Lifter Lookup** — name search with history plot against QT reference lines, plus manual entry for hypothetical trajectories.
4. **QT Squeeze** — unified filter-panel view of CPU + all 10 provincial qualifying total coverage. All 10 provinces routed (6 scraped, 2 via CPU Regional, 2 open-entry).
5. **About** (hidden from primary nav as of 2026-04-26 until publish-ready) — full methodology, live backtest MAPE table + ship-gate status (rendered from `frontend/src/data/backtest_results.json`), references, and disclaimers. Still linked from every other tab's methodology block; route resolves via `?tab=about`.

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

See the "Pre-push checklist" section further down (line ~150) for the
full commands. Summary: `npm run build`, `python -m pytest backend/tests/`,
`npm run test` (Vitest), optionally `npm run test:e2e` (Playwright local).

## URL state conventions

Every user-facing, shareable view is encoded in `window.location.search` via the
`useUrlState` hook in `frontend/src/lib/useUrlState.ts`. Keys are omitted from
the URL when they equal their default, so a pristine page has a clean URL.

Supported URL keys (as of 2026-04):

| Key | Scope | Example values |
|---|---|---|
| `tab` | App shell | `progression`, `projection`, `qt`, `lookup`, `about` |
| `sex`, `weight_class`, `equipment`, `tested`, `event`, `division`, `age_category`, `x_axis` | Progression filters | `M`, `83`, `Raw`, `Yes`, `SBD`, `Open`, `All`, `Years`, `Career quartile` |
| `mode` | Lifter Lookup | `search`, `compare`, `manual` |
| `lifter` | Lifter Lookup search mode | `Matthias Bernhard` |
| `lifters` | Lifter Lookup compare mode | `Matthias Bernhard,Alex Mardell` (up to 4) |
| `era` | Lifter Lookup | `pre2025`, `2025`, `2027` |
| `view_mode` | Lifter Lookup | `total`, `per_lift` |
| `range` | Lifter Lookup compare | `all`, `6`, `12`, `24`, `60` |
| `ap_name`, `ap_horizon`, `ap_qt_year` | Athlete Projection | `Matthias Bernhard`, `12`, `2027` |

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
- **Career quartile x-axis skips projection.** When `x_axis == 'Career quartile'`, `compute_progression` short-circuits the trendline computation because the axis is a normalized index (Q1-Q4), not an elapsed time. A kg/day slope over quartiles would be meaningless. Other axes (Meet #, Days, Weeks, Months, Years) still compute + return the dashed trendline. Quartile bucketing is `np.floor((DaysFromFirst / career_span) * 4) + 1` clipped to [1, 4], grouped per-lifter via pandas `groupby.transform`. Shipped 2026-04-23 in commit `6e96358` (PR #11).
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
- **CompareView is lazy-loaded.** `const CompareView = lazy(() => import('./CompareView'))` in `LifterLookup.tsx`. Ships as its own ~11 KB chunk. Do NOT add a static import from CompareView back into LifterLookup - it will defeat the split (vite warns `INEFFECTIVE_DYNAMIC_IMPORT`).
- **LifterDetail is lazy-loaded.** `const LifterDetail = lazy(() => import('./LifterDetail'))` in `LifterLookup.tsx`. The whole detail view (chart + meet table + ClassChangeBadge + fmtDate/Kg/Sbd formatters + findQtForLifter + EVENT_DESCRIPTION + Era maps) lives in `frontend/src/tabs/LifterDetail.tsx` and ships as its own ~18 KB chunk. Both usages (search-mode and ManualEntryForm result block) are wrapped in `<Suspense fallback={<LoadingSkeleton lines={3} chart />}>`. Do NOT add a static import from LifterDetail.tsx back into LifterLookup.tsx — that would re-merge the lazy chunk into the main bundle. Recharts (~357 KB CartesianChart chunk) is now shared between CompareView and LifterDetail and only loads when either opens. Main bundle went from ~663 KB to 295.61 KB (-55%) in commit that landed 2026-04-20.
- **Recharts + display:none (resolved via isActive prop).** Inactive tabs render with `display:none` at the wrapper level so tab-internal state (scroll, dropdown, typed search) survives switches. Each tab component takes an `isActive: boolean` prop from `App.tsx` and gates its `ResponsiveContainer` subtree with `{isActive && <ResponsiveContainer>...</ResponsiveContainer>}`. Fix landed 2026-04-21 in commit `cd5e579`. Pattern applies to `Progression.tsx`, `QTSqueeze.tsx` (four instances), `LifterDetail.tsx` (two), `CompareView.tsx` (one). `LifterLookup.tsx` threads `isActive` through to its lazy children. `AthleteProjection.tsx` accepts the prop for future charts. Do NOT reintroduce a ResponsiveContainer render outside the `{isActive && ...}` gate, and do NOT remove the display:none wrapper (that would break state preservation on tab switches). Residual Recharts console noise: width(0) height(0) fires once per chart on its very first render before ResizeObserver measures the container. Orthogonal to the display:none problem and not worth fixing — it's the Recharts init cycle, not a layout bug.
- **Dots renamed to Goodlift through the SQL pipeline.** `backend/app/lifters.py` selects `Goodlift`, not `Dots`. If the locally preprocessed parquet was generated before the rename, `/api/lifter/history` returns 503 with `duckdb_error: column Goodlift not found`. Fix: re-run `python data/preprocess.py` to regenerate. The data_loader corrupt-parquet self-heal only checks row-count > 0, not schema completeness, so a stale-schema parquet will keep being served. See NEXT_STEPS.md Issue 16.
- **Parallel-chat hook sweep risk.** When multiple Claude Code chats stage changes to the same worktree simultaneously, a concurrent commit hook or agent can sweep unrelated staged files into a single commit with only one chat's message. This happened three times on 2026-04-17 alone: Chat A's per-lift `main.py` inside Chat B's `e7432f5`, scroll-fix inside tooltip commit `24dadb5`, and an NEXT_STEPS.md stash/pop during the CI landing `12cbb46`. Mitigation: run parallel chats in git worktrees, not the same checkout, or dispatch serially. See `~/.claude/rules/common/parallel-chat-isolation.md`.
- **OPA landing page requires the Brotli Python package.** The Wix CDN serving `ontariopowerlifting.org` only emits `Content-Encoding: br` regardless of what `Accept-Encoding` the client sends. Without `Brotli>=1.1` installed (it's a requests-optional dep), `requests.text` silently returns undecoded bytes and the xlsx URL regex in `data/scrapers/opa.py` finds nothing, producing a misleading "OPA likely changed their page structure" warning that graceful-degrades to an empty Ontario slice. Brotli is now pinned in `backend/requirements.txt` and `discover_xlsx_url()` has a decoded-HTML sanity check that raises a clearer error if the decoder goes missing again. Do NOT remove Brotli from requirements without finding another way to decode the response body.
- **Meet table does NOT scroll horizontally.** `LifterLookup.tsx:628` wraps the meet table in a plain `<div className="mt-6">` with NO `overflow-x-auto`. The Sq/Bn/Dl triplet cell (~line 704) and the Sq/Bn/Dl % cell (~line 716) deliberately omit `whitespace-nowrap` so big-number rows wrap within their column instead of pushing the table wider than the container. Short cells (Date, Event chip, Class) keep `whitespace-nowrap`. Do NOT reintroduce `overflow-x-auto` on this wrapper. If a future column genuinely needs nowrap, add it to that cell only, never to the wrapper.
- **ClassChangeBadge uses a React portal.** The amber class-change triangle in the meet table renders its hover tooltip through `createPortal(..., document.body)` so the tooltip escapes any table-cell stacking context or future `overflow` clip. Pattern is defensive: even though the wrapper no longer clips, keeping the portal means the tooltip survives a future wrapper change. See `LifterLookup.tsx:46-81`.
- **Methodology disclaimer convention.** Every user-facing tab ships a collapsed `<details>` block titled either "Methodology notes" or "Methodology and caveats" with consistent styling: `<summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">`, inner `<div className="text-zinc-500 text-xs mt-2 space-y-1.5">`, each caveat as a `<p>` with a `<span className="text-zinc-400 font-medium">` lead-in label. Landed in commit `61d010c` across Progression, Lifter Lookup top-level, Manual entry form, Compare mode, and QT Squeeze. Athlete Projection BETA has its own MethodologyBlock inside `AthleteProjection.tsx` following the same pattern (see commit `651ced6`). Do NOT invent a new visual style for a new tab's disclaimer, reuse the pattern.
- **Athlete Projection cohort is 2D (age division x GLP bracket).** `backend/app/athlete_projection.py` precomputes 231 cells at FastAPI startup (7 age divisions x 11 GLP brackets x 3 lifts). Each `GlpCohortCell` stores the mean Huber slope across lifters in that cell. Sparse cells (< 20 lifters) merge upward first, then downward, within the same division. A whole-division fallback kicks in when total n < 20 across all brackets for a lift. The merge + fallback decisions are logged at startup (grep `[athlete_projection] merged`). Cache lookup is `get_cohort_cell(division, bracket, lift)`. Do NOT re-introduce the old `predict(level)` or level-conditioned continuous slope fit -- it was replaced in `045caed` after the Sean Yen pivot.
- **IPF-GL coefficients live in `backend/app/ipf_gl_points.py`.** Raw SBD only for v1. Men: A=1199.72839 B=1025.18162 C=0.00921025. Women: A=610.32796 B=1045.59282 C=0.03048. `ipf_gl_points(total, bw, age, sex)` returns None on any null or non-positive input and on unknown sex. Age is accepted in the signature but IPF-GL does NOT apply an age adjustment -- age is reserved for a possible Masters-adjustment layer later. Bracket edges and labels also live here (`GLP_BRACKET_EDGES`, `GLP_BRACKET_LABELS`).
- **Bracket transitions use a two-pass projection.** `shrinkage_projection` projects all three lifts using the initial bracket first. If the pass-1 total crosses a bracket edge during the horizon, pass 2 rebuilds each lift with a per-segment cohort cell from `_compute_brackets_per_point`. The personal slope stays constant across segments; only the cohort contribution changes. Small discontinuities at boundaries are expected and documented on the About page. No smoothing for v1.
- **Engine D (MixedLM) toggle is gated off.** `mixed_effects_projection` delegates to shrinkage and stamps `meta.engine_d_available=false`. The frontend `AthleteProjection.tsx` hides the Simple/Advanced radio via `{false && <EngineToggle ...>}` until the MixedLM wiring lands. Convergence probe ran 2026-04-27 (`data/probe_mixedlm_convergence.py`) and cleared the realistic-floor pass at 91.7% once Engine C's bracket-merge ladder was applied (commit `619d431`); raw cells without merging only had 1 of 77 fittable. Session B-2 ships the wiring with two guardrails: per-cell fallback to Engine C slope on non-converge, `engine_d_available=True` only when live precompute >= 90%. Probe artifact at `data/processed/mixedlm_convergence_probe.json` (gitignored). See memory `feedback_probe_must_mirror_production_path.md`.
- **Athlete Projection division fallback.** `_assign_division` tries the most recent meet's `Age`, then any non-null `Age` in the lifter's history, then the free-text `Division` column via `_DIVISION_TEXT_MAP`, then defaults to `Open`. ~70% of rows have NULL Age in the Canada+IPF parquet, so without this cascade the projection endpoint would return `found=false` for most lifters. Division mapping handles common OpenIPF spellings (`Masters 40-49` -> `M1`, `Sub-Juniors` -> `Sub-Jr`, etc.) but is not federation-portable beyond CPU/IPF.
- **Athlete Projection per-lift history.** Each `LiftProjection` in the `/api/athlete/{name}/projection` response carries a `history` array of `{date, days_from_first, kg}` rows, one per meet that contested that lift. Origin is the lifter's first meet of that specific lift (not the first SBD meet), matching the `days_from_first` scale used by `projected_points` so the frontend can plot both on the same x-axis without further offset. The per-lift Athlete Projection chart overlays these as blue scatter dots + a seam point that joins history to the projection line. Landed in commit `98b57d8`.
- **Athlete Projection QT reference lines.** Optional on the Total view only (per-lift QTs do not exist). **Migrated to live QT feed 2026-04-23** in commit `3cc8147` (PR #13). Reuses `fetchQtLiveFilters()` + `fetchQtLiveCoverage()` from the QT Squeeze tab instead of the historical `fetchQtStandards()`. Effective-year picker filtered to years >= 2026 because CPU Nationals/Regionals only exist from 2026 onward in the live feed (NLPA publishes 2022 standards but that is provincial and out of scope here). Regionals query pinned `region='Western/Central'` until CPU publishes non-Western Regionals. Historical era picker retired. URL key renamed `ap_qt_era` to `ap_qt_year`. Recharts v3 defaults `ifOverflow` to `discard` on ReferenceLine, which silently drops lines whose y is outside the auto-domain; `ifOverflow="extendDomain"` is load-bearing and must not be removed. Original era-picker implementation landed in commit `8452835`.
- **Precompute startup cost -- serialization shipped 2026-04-23** (PR #10). `serialize_tables` / `load_serialized_tables` in `backend/app/athlete_projection.py` persist the 231 cohort cells + 7 K-M tables as JSON (~61 KB, schema v1). `data/preprocess.py` emits the artifact on every data refresh and `.github/workflows/refresh-data.yml` uploads it to the `data-latest` GitHub Release. Render env var `ATHLETE_PROJ_TABLES_URL` lets the backend download it at startup instead of re-fitting. The `[startup] athlete_projection tables: loaded from disk cohort_cells=... km=... elapsed_ms=...` log line confirms the disk-load path. On Render the elapsed went from ~200,698 ms (refit) to ~2 ms (disk-load). If the schema changes, bump `SERIALIZED_TABLES_SCHEMA_VERSION` so stale artifacts are rejected and the lifespan falls back to live fit. The live-fit fallback path is retained for safety and for local dev without the env var. Merged-alias preservation is load-bearing: multiple dict keys can legitimately point to the same `GlpCohortCell` after bracket merging, so serialization emits `key_bracket` per row separately from `cell.glp_bracket`, and load interns cells by identity tuple. Locked by `test_round_trip_preserves_merged_alias_identity`.
- **Timedelta-to-days conversion.** Pandas 3.0 + numpy 2.4 on Python 3.14 refuse `(dates - first).astype("timedelta64[D]").astype(float)` -- the supported resolutions are s/ms/us/ns. Use `((dates - first) / np.timedelta64(1, "D")).astype(float)` instead. Both patterns appear historically; new code must use the division form. See `athlete_projection.py` for the pattern.
- **Backtest is offline-only.** `data/backtest_projection.py` walks forward over lifters with >= 15 SBD Raw meets, holds out last 3, projects via Engine C, and reports MAPE at 3/6/12/18 months vs log-linear and Gompertz baselines. NOT imported by any production module, NOT in CI. Artifact at `data/backtest_results.json` is committed for the About page. Ship gates: Engine C MAPE < 6% at 6mo, < 12% at 12mo; Engine C must not lose by > 2pp to alternatives at 12mo. Baseline (50-lifter Canada+IPF sample, commit `32918ad`) passes all gates.
- **Render env var pinning enforced in CI.** Every `os.environ.get("*_URL")` call in `backend/app/` must have its key pinned in `render.yaml` under `envVars`. Enforced by `scripts/check_env_var_pinning.py`, run in the backend CI job before pytest. The pattern matters because env vars set only in the Render dashboard get silently dropped on a Blueprint re-provision, which surfaces as the corresponding feature regressing to its empty state. Rule landed 2026-04-26 after `QT_CURRENT_CSV_URL` (and `ATHLETE_PROJ_TABLES_URL` three days earlier) shipped through that exact failure mode. Same-day fix path when the check fires: (1) add `- key: <NAME>` plus `value: <url>` to render.yaml envVars, (2) verify in the Render dashboard the live value matches, (3) commit. To intentionally exclude a var (local-dev-only, etc.), add it to `ALLOWLIST` in the script with an inline reason comment.

## Pre-push checklist

- `cd frontend && npm run build` -- catches TypeScript strict errors.
- `cd cpu-analytics && .venv/Scripts/python -m pytest backend/tests/ -v` --
  326 backend tests (174 baseline + 47 Engine C + 23 IPF-GL + ~70 QT
  scraper fixtures + 12 added in subsequent rounds), 1 skipped, covering
  progression, lifters, projection, athlete projection, QT (federal +
  provincial scrapers), manual entry, security, weight class Hypothesis,
  and concurrency. Always use `python -m pytest`, NOT plain `pytest`, or
  the `backend.app` imports fail with `ModuleNotFoundError`.
- `cd frontend && npm run test` -- 16 Vitest unit tests (3 useUrlState
  key collisions + 10 MethodPill cross-nav picker + 3 Banner tone
  classes). Runs in jsdom, ~2 s.
- `cd frontend && npm run test:e2e` -- 6 Playwright smoke tests. Now
  also runs in CI via the `e2e` job (Arc 7, commit `166c5ff`) with
  `continue-on-error: true` until the suite is hardened. Requires
  `npx playwright install chromium` on first local run.
- CI runs three parallel jobs on every push and PR via
  `.github/workflows/ci.yml`: frontend (tsc+build), backend (pytest),
  e2e (Playwright). A local failure will also fail CI, so fix before
  pushing rather than relying on the remote run.

## Scope

Backend defaults enforce Country=Canada, ParentFederation=IPF (see `backend/app/scope.py`). Widening is a one-line change. Do not remove the defaults silently — the entire product framing is CPU/IPF.

## Data pipeline invariants

- `data/preprocess.py` writes `openipf.parquet` + `qt_standards.parquet` to `data/processed/` (gitignored).
- Production containers download these two files from the `data-latest` GitHub Release on first request (`backend/app/data_loader.py`).
- `data/qualifying_totals_canpl.csv` is vendored into git (32 rows, hand-curated). Historical pre-2025 / 2025 values only. CI needs it available without the 285 MB OpenIPF CSV. Once the live QT pipeline (see below) is wired through, this file is also the bootstrap fallback when the scraped CSV can't be fetched.
- **Live QT scraper** (Phase 1a + 1b + 1c-backend + 1c-frontend-MVP shipped 2026-04-21). `data/scrapers/cpu.py` parses CPU qualifying-total PDFs from powerlifting.ca via pdfplumber. Shared schema + validation at `data/scrapers/base.py`. Orchestrator at `data/scrape_qt.py` (CLI: `--once --output-dir OUT [--existing CSV]`, `--dry-run`, `--regenerate-fixtures`). Fixture tests at `backend/tests/test_scrape_qt.py` lock parser output row-for-row. Scope: Classic + SBD only; Equipped and Bench Only filtered out by orchestrator.
- **Weekly QT refresh workflow** at `.github/workflows/qt_refresh.yml`: Sundays 06:43 UTC + manual dispatch. Downloads last-published `qt_current.csv` from the `data-latest` release, reruns scraper, and on diff: uploads new CSV, opens an issue with the row-level diff, commits a snapshot to `data/qt_history/YYYY-MM-DD.csv`. Uses default `GITHUB_TOKEN`; no new secrets.
- **Live QT backend** at `backend/app/qt_data_loader.py` + `backend/app/data.py`. Registers a DuckDB view `qt_current` over the scraped CSV if present, otherwise the view is absent and `is_qt_current_available()` returns False. `backend/app/qt.py` adds `load_live_qt`, `get_live_qt_filters`, `compute_live_coverage(sex, level, effective_year, division, region, equipment, event)`. Cohort = 24-month window ending March 1 of the effective year. Endpoints: `/api/qt/live/filters`, `/api/qt/live/coverage`. Legacy `/api/qt/coverage` and `/api/qt/blocks` are untouched and keep reading from `qt_standards.parquet` for the pre-2025 / 2025 historical narrative.
- **Live QT frontend (unified view)** at `frontend/src/tabs/QtLiveCoveragePanel.tsx`, now the sole view in the QT Squeeze tab. Filter panel: Sex, Level (Nationals / Regionals / Provincials), Division, Effective year, conditional Region (2027 Regionals) or Province (Provincials). `QTSqueeze.tsx` is a thin 77-line wrapper (header + methodology details + panel). The old four-block layout was retired 2026-04-22 in commit `da4fa24`; its logic was bound to the historical pre-2025 / 2025 narrative, which is now superseded by the live feed. Main bundle dropped from 309 KB to 288 KB as Recharts BarChart usage left the tab.
- **OPA Ontario provincial scraper** at `data/scrapers/opa.py` (Phase 2, SHIPPED 2026-04-22). Discovers the Dropbox-hosted Qualifying-Standards.xlsx URL from `ontariopowerlifting.org/qualifying-standards` (URL rotates on each upload; must rediscover every run). Parses the Classic sheet only. Schema extended with `province` column and `Provincials` level; `base.validate_row` enforces that Provincials rows have province set and federal rows have province=None. Orchestrator runs CPU + OPA back-to-back with the OPA failure non-fatal (federal CSV still publishes). Current output: 696 in-scope rows (580 federal + 116 Ontario).
- **Provincial landscape** (2026-04-22 audit + full build-out): all 10 provinces routed. Scraped: Ontario (`opa.py`, Dropbox xlsx), Manitoba (`mpa.py`, PDF), Nova Scotia (`nspl.py`, Google Sheet gviz CSV), Newfoundland (`nlpa.py`, .docx via Google Docs export + staleness warning), Alberta (`apu.py`, hash-verified manual transcription under `apu_transcribed/<year>/` -- APU only publishes JPGs, so OCR was swapped for hash-matched human transcription to protect data integrity), Quebec (`fqd.py`, JSON API at `sheltered-inlet-15640.herokuapp.com/api/v1/standards` -- the React SPA exposes its backend directly so Playwright was never required). Routing-only in the frontend `QtLiveCoveragePanel.tsx` PROVINCE_CATALOGUE: BC + SK resolve to CPU Regional Western with an amber "defers to CPU" banner; NB + PE suppress the backend call and render an open-entry notice. NSPL invariant locked by test: do NOT derive NSPL = 0.9 x CPU Regional because NSPL rounds up to 2.5 kg after multiplying (~11 rows/year diverge by +1.25 kg).

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

**326 pytest + 16 Vitest + 6 Playwright passing.** Pytest covers
progression, lifters, projection, athlete projection (Engine C +
IPF-GL), qt (federal + OPA + MPA + NSPL + NLPA + APU + FQD parsers),
manual, security, weight_class (with 19 Hypothesis property tests), and
concurrency modules. Athlete Projection BETA added 70 tests across
`test_athlete_projection.py` and `test_ipf_gl_points.py` (commits
`02b9e43`, `dd9c3cc`, `58b7c7d`); QT scraper fixtures added ~70 tests
in `test_scrape_qt.py`. Vitest (added 2026-04-20, commit `84a7ea7`)
covers useUrlState key-collision warnings + MethodPill cross-nav picker
(added 2026-04-26, commits `189bfdc`/`0a5a3bc`). Playwright (commit
`454f1de`, wired into CI Arc 7 commit `166c5ff`) covers 6 smoke flows.

**CI is now enforcing on main.** `.github/workflows/ci.yml` (commit
`12cbb46`) runs frontend `tsc + npm run build` and backend `pytest` in
parallel on every push and PR to main. Classic branch protection rule
requires the `Frontend (tsc + build)` check to pass before merge. Backend
check exists but is not yet required (see NEXT_STEPS.md). Expect ~3 min
wall-clock per CI run.

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

- **Data refresh Run #7 verified Success 2026-04-21.** data-latest
  release updated with Canada+IPF-filtered parquet including Goodlift
  column. Live site renders cleanly.
- **Branch protection CLOSED 2026-04-21.** Classic rule on `main` now
  requires both `Frontend (tsc + build)` and `Backend (pytest)`. Admin
  bypass retained.
- **Skew Protection (Issue 11)** is Pro-only on Vercel. Parked as a
  strategic decision until traffic justifies $20/mo.
- **Render cold-start strategy (Issue 12) DECIDED 2026-04-21.** Staying
  on Render free tier with keepalive cron. Fly Machines free tier
  requires a credit card which the user declined to add. Upgrade path
  to Render Hobby $7/mo is queued for if keepalive misses become
  user-visible.

### High-priority code work

1. **Lazy-load `LifterDetail`** — SHIPPED 2026-04-20. Main bundle dropped
   from 663 KB to 295.61 KB (-55%). Recharts now lives in a shared 357 KB
   CartesianChart chunk that only loads when CompareView or LifterDetail is
   opened. LifterDetail ships as its own 18 KB chunk.
2. **Per-lift filter plumbing.** Frontend shows an amber warning that per-lift
   view ignores age_category, same_class_only, and max_gap_months. Data-correctness
   gap. Extend `compute_lift_progression` to accept and apply those filters
   (including baseline recomputation for age_category).

### Medium-priority features

3. **Bodyweight + Goodlift progression curves.** SHIPPED 2026-04-20
   (commit `fca221e`). Metric selector on the Progression tab
   (TotalKg / Bodyweight / Goodlift). 9 new pytests (165 -> 174).
4. **Compare chart summary cards + QT reference lines.** SHIPPED
   2026-04-20 (commit `0e9f0ba`). Per-lifter cards and optional QT
   reference line set on CompareView.
5. **Coach "on pace for Nationals 2027" widget.** UNBLOCKED, not
   started. Fills the Athlete Projection BETA placeholder using the
   existing linear individual projection. Does NOT require the P3
   weighting decision (which is now backburnered pending Matthias's
   statistics consultation). UI-only change in `AthleteProjection.tsx`.
   ~1 focused session.
6. **Monitor RSS after next cold start.** Look at Render logs for the
   `[startup] process RSS: <MB>` line to quantify the G2 memory improvement.

### Low-priority / polish

7. **Hypothesis property-based tests** for `canonical_weight_class` — SHIPPED (commit `cb7038e`, 19 tests).
8. **Extract LifterDetail to its own file** — SHIPPED 2026-04-20 alongside the lazy-load.
9. **UptimeRobot dashboard verification** once HEAD is live (pending user
   manual navigation since the Chrome extension blocks dashboard domains).
10. **useUrlState collision Vitest** — SHIPPED 2026-04-20 (commit `84a7ea7`, 3 tests).
11. **Playwright E2E smoke scaffold** — SHIPPED 2026-04-20 (commit `454f1de`, 6 tests, local only).
