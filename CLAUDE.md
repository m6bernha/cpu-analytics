# CLAUDE.md — Project guide for cpu-analytics

This file is for Claude Code sessions. Read it at the start of any session in this repo.

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

**Phases 7-9 remaining:**
- Phase 7: Weight class migration tracking (detect class changes, filter to same-class-only careers)
- Phase 8: Prediction/extrapolation (individual trajectory projection, cohort confidence intervals, percentile rank)
- Phase 9: Per-lift progression (separate S/B/D curves for cohort + individual, bench-only meets feed the bench curve)

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
