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

## Known gotchas

- **Recharts v3.8 strict types.** `Tooltip` formatter/labelFormatter callbacks receive `ValueType | undefined` and `ReactNode` for label. Do not annotate params as `number` / `string`. See `cpu-analytics/frontend/src/tabs/*.tsx` for the pattern.
- **Render cold start.** First request after 15 min idle takes up to ~50 s. UptimeRobot (free) pinging `/api/health` every 5 min keeps it warm.
- **Vercel auto-detects the repo as a multi-service project** because both `frontend/` and `backend/` are present. On new project import, set **Root Directory = `frontend`** to force single-service Vite mode. `vercel.json` lives inside `frontend/`, not at repo root.
- **Tested filter has one value.** The OpenIPF export is IPF-only, every row is `Tested=Yes`. The filter dropdown should be hidden or replaced with a static note.
- **Age column is ~70% NULL.** Any age_category filter silently drops many rows. The Progression tab shows a hint about this.
- **Division is free-text.** `Division='Open'` works for CPU specifically, verified empirically (see `backend/app/qt.py` comments). Not federation-portable.
- **Weight class canonicalization** collapses historical 1-kg-off variants into modern IPF classes. See `backend/app/weight_class.py`. Fine in aggregate, wrong at the individual level for some edge cases.

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

## When extending this

- New API endpoint: add to `backend/app/main.py`, wire a module in `backend/app/`, add a typed fetcher in `frontend/src/lib/api.ts`.
- New tab: add a component in `frontend/src/tabs/`, register in `frontend/src/App.tsx`'s `TABS` array and switch.
- New filter: add the enum in `backend/app/filters.py` if it's enumerable, and a `<Select>` in `Progression.tsx` (or wherever it applies).
