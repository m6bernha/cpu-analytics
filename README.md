# CPU Powerlifting Analytics

**Live app:** https://cpu-analytics.vercel.app

A web app that turns the OpenPowerlifting dataset into four primary views a
Canadian raw powerlifter actually uses: cohort progression, per-lifter
Bayesian-shrinkage projection, per-lifter history, and CPU qualifying-total
coverage (federal + provincial). An About page with full methodology and
live backtest MAPE is accessible via `?tab=about` while it's being finalized.

Scoped to Canadian lifters in IPF-sanctioned meets (CPU domestic and IPF
international). Data refreshed weekly from
[OpenPowerlifting](https://openpowerlifting.org/)'s OpenIPF bulk export.

[![CI](https://github.com/m6bernha/cpu-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/m6bernha/cpu-analytics/actions/workflows/ci.yml)
[![Data refresh](https://github.com/m6bernha/cpu-analytics/actions/workflows/refresh-data.yml/badge.svg)](https://github.com/m6bernha/cpu-analytics/actions/workflows/refresh-data.yml)
[![Keepalive](https://github.com/m6bernha/cpu-analytics/actions/workflows/keepalive.yml/badge.svg)](https://github.com/m6bernha/cpu-analytics/actions/workflows/keepalive.yml)

---

## Why this exists

Three real questions Canadian raw lifters ask, and none of the existing
dashboards answer cleanly:

1. **Is a 10 kg gain in a year good or bad for my class and age?** Comparing
   yourself to a cohort requires the cohort to actually match your class,
   equipment, division, and age bracket. OpenPowerlifting has the data but
   filters to the whole world and all federations by default.
2. **Do I have a realistic shot at Nationals 2027 given the new qualifying
   totals?** The CPU raised standards across the board starting in 2025 and
   will raise them again in 2027. Knowing the percent of Open lifters who
   currently meet each standard makes the bar concrete.
3. **What does the full trajectory of lifters who DID qualify look like?**
   Plotting a single lifter's meet-by-meet history against the exact QT
   reference lines for their class turns "am I on pace" from a vibe into
   a number.

The OpenPowerlifting data is under CC0 and publicly available. The gap this
app fills is the Canadian-IPF scope plus the CPU-specific qualifying-total
reference points.

---

## What it does

Five tabs, each answering one concrete question. All views share filters for
sex, weight class, equipment, event, division, and age bracket, and URL state
is shareable (every meaningful view has a clean permalink).

### 1. Progression — "how much do lifters like me gain over time?"

Average total improvement across a cohort, plotted over a time axis of your
choice (months since first meet, years since first meet, or calendar date).
Weighted OLS trendline with R-squared. Standard-deviation band around the
mean so the noise is visible, not hidden. Optional per-lift breakdown
(squat, bench, deadlift) and a comeback filter that excludes lifters with
long inter-meet gaps.

### 2. Athlete Projection (BETA) — "where will my total be in two years?"

Per-lift Bayesian-shrinkage projection (Engine C) stratified by age division
and IPF-GL bracket. Personal Huber slope blended with a cohort posterior that
comes from 231 precomputed cells (7 divisions x 11 GLP brackets x 3 lifts).
Kaplan-Meier dropout-adjusted prediction intervals widen with horizon.
Optional CPU QT reference lines driven by the live qualifying-total feed.
Full methodology and live backtest MAPE on the About tab.

### 5. About — "how does this work and how well?"

Full methodology notes for every tab, live backtest MAPE table rendered from
`data/backtest_results.json`, ship-gate status, data source attribution, and
disclaimers. Linked from every other tab's methodology block.

### 3. Lifter Lookup — "plot my own trajectory against the QT lines"

Search by name and see every meet plotted with CPU qualifying-total
reference lines for the lifter's weight class. Per-meet bodyweight, Goodlift
(GLP) score, rate-of-improvement regression, PR detection, and a class-change
indicator when the lifter moves between weight classes.

Three modes:
- **Search**: single lifter, full history, projection overlay.
- **Compare**: up to four lifters side-by-side on a shared axis.
- **Manual**: enter hypothetical meets for lifters not in the dataset, or
  project a planned total at a future date.

### 4. QT Squeeze — "what percent of Open lifters meet the new standard?"

Four-block table (men's Nationals, men's Regionals, women's Nationals,
women's Regionals) showing the fraction of Open lifters whose 24-month-best
total clears each era's qualifying standard: pre-2025, 2025, and the
forward-looking 2027 cutoff. Answers "how hard did they just make it, and
how hard is it about to get" in one view.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + DuckDB over Parquet, Python 3.12 in prod |
| Frontend | Vite + React 19 + TypeScript (strict) + TanStack Query + Recharts + Tailwind v3 |
| Data pipeline | GitHub Actions weekly cron + pandas preprocess |
| Backend hosting | Render.com (free tier, Docker, `render.yaml` blueprint) |
| Frontend hosting | Vercel Hobby (auto-deploy on push to `main`) |
| Tests | pytest + Hypothesis (314 passing) + Vitest (3 passing) + Playwright local (6 smoke); Vite build as frontend gate |
| CI | GitHub Actions build-gate on every push and PR |
| Uptime | UptimeRobot HEAD ping + GHA cron keepalive |

---

## Architecture at a glance

```
         weekly cron                          cold-boot download
OpenPowerlifting ---> [preprocess.py] ---> [GitHub Release] ---> [Render: FastAPI + DuckDB]
                                                                        |
                                                                        |  REST /api/*
                                                                        v
                                                               [Vercel: React SPA] <--- user
```

Full system design and decision log: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Data pipeline, QT standards, scope enforcement: [docs/DATA.md](docs/DATA.md).

---

## Scope

The app intentionally restricts queries to:

- **Country = Canada**
- **ParentFederation = IPF** (CPU domestic and IPF international meets)

The restriction is applied twice: once at preprocess time (the shipped
parquet is pre-filtered, roughly 15-20x smaller than the full OpenIPF
export, about 5,400 lifters) and again at every API query
(`backend/app/scope.py`). Widening the scope is a one-line change, but the
product framing is CPU-centric by design.

Weight classes are canonicalized to modern IPF (59/66/74/83/93/105/120/120+
for men, 47/52/57/63/69/76/84/84+ for women). Historical 1kg-off variants
collapse into their current class. Men below 58 kg drop from QT views
because no CPU QT standard exists for that range.

---

## Live endpoints

| Service | URL |
|---|---|
| Frontend | https://cpu-analytics.vercel.app |
| Backend | https://cpu-analytics-backend.onrender.com |
| Liveness | https://cpu-analytics-backend.onrender.com/api/health |
| Readiness | https://cpu-analytics-backend.onrender.com/api/ready |
| OpenAPI docs | https://cpu-analytics-backend.onrender.com/docs |

Render's free tier spins down after 15 minutes of idle traffic. A cold start
is 20-50 seconds. UptimeRobot and a GitHub Actions cron ping `/api/health`
every 5 minutes to keep the instance warm during normal hours.

---

## Local development

### One-time setup

```bash
# Backend
cd cpu-analytics
python -m venv .venv
.venv/Scripts/activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r backend/requirements.txt

# Data
# Download openipf-latest.zip from
# https://openpowerlifting.gitlab.io/opl-csv/files/openipf-latest.zip
# Unzip it and point preprocess.py at the CSV:
python data/preprocess.py

# Frontend
cd frontend
npm install
```

### Running locally

```bash
# Terminal 1 - backend
cd cpu-analytics
.venv/Scripts/activate
uvicorn backend.app.main:app --reload

# Terminal 2 - frontend
cd cpu-analytics/frontend
npm run dev
```

Frontend runs at http://localhost:5173 and expects the backend at
http://127.0.0.1:8000. Override with `VITE_API_BASE` env var.

### Tests

```bash
# Backend tests (314 passing)
.venv/Scripts/python -m pytest backend/tests/ -v

# Frontend unit tests (3 Vitest passing)
cd frontend && npm run test

# Frontend E2E smoke (6 Playwright tests, local only, needs
#   `npx playwright install chromium` on first run)
cd frontend && npm run test:e2e

# Frontend strict typecheck + production build
cd frontend && npm run build
```

Both commands also run in CI on every push and PR.

---

## Data refresh

`.github/workflows/refresh-data.yml` runs every Sunday at 06:13 UTC:

1. Downloads the latest OpenIPF bulk CSV from
   `openpowerlifting.gitlab.io/opl-csv/files/openipf-latest.zip`.
2. Runs `data/preprocess.py` to produce `openipf.parquet` (Canada + IPF
   filtered), `qt_standards.parquet` (hand-curated CPU standards), and
   `athlete_projection_tables.json` (serialized 231-cell Engine C cohort +
   7 K-M tables, ~61 KB).
3. Publishes all three files as the rolling `data-latest` GitHub Release.

A second weekly workflow `qt_refresh.yml` (Sundays 06:43 UTC) scrapes the
live CPU + provincial qualifying totals and produces `qt_current.csv`.

The production backend reads `OPENIPF_PARQUET_URL`, `QT_PARQUET_URL`,
`QT_CURRENT_CSV_URL`, and `ATHLETE_PROJ_TABLES_URL` env vars to fetch the
latest artifacts on cold start. The Athlete Projection tables artifact
drops cold-start fit elapsed from ~200 s to ~2 ms on Render free tier.

Manual refresh: Actions tab -> "Refresh OpenIPF data" -> Run workflow.

Full data-flow details: [docs/DATA.md](docs/DATA.md).

---

## Deployment

### Backend: Render

Dockerized via the repo-root `Dockerfile` and `render.yaml` blueprint.
Health-check path: `/api/health` (GET and HEAD both work so the free-tier
probe and UptimeRobot's HEAD-only free plan both succeed). Readiness probe
at `/api/ready` runs `SELECT 1` against DuckDB.

### Frontend: Vercel

Vercel imports the repo with **Root Directory = `frontend`**. `vercel.json`
lives inside `frontend/`, not at repo root. Auto-deploys on every push to
`main`. Set the `VITE_API_BASE` env var to the Render backend URL.

---

## Repo layout

```
cpu-analytics/
  backend/
    app/
      main.py            FastAPI app, routes, lifespan, middleware
      data.py            DuckDB singleton + per-request cursor helpers
      data_loader.py     Cold-boot download of parquet from GitHub Release
      scope.py           Country + ParentFederation defaults (Canada + IPF)
      filters.py         /api/filters enumerated values
      progression.py     Cohort aggregation + projection math
      qt.py              QT coverage + four-block view
      lifters.py         Search + per-lifter history
      manual.py          Manual-entry trajectory builder (validated)
      weight_class.py    Canonical M/F class mapping
    tests/               pytest + Hypothesis (158 tests)
    requirements.txt
  data/
    preprocess.py        CSV -> Parquet, applies Canada+IPF filter
    qualifying_totals_canpl.csv   Hand-curated CPU QT standards (vendored)
    processed/           Gitignored output
  frontend/
    src/
      App.tsx            Tab shell + URL-backed routing
      lib/
        api.ts           Typed fetch helpers
        useUrlState.ts   URL-backed state hook
        QueryStatus.tsx  Shared loading/error components
      tabs/
        Progression.tsx
        AthleteProjection.tsx
        LifterLookup.tsx  (hosts Compare mode via lazy import)
        CompareView.tsx
        QTSqueeze.tsx
    package.json
    vercel.json
  docs/
    ARCHITECTURE.md
    DATA.md
  .github/workflows/
    ci.yml               Frontend build + backend pytest
    refresh-data.yml     Weekly OpenIPF refresh
    keepalive.yml        Render cold-start mitigation
  CLAUDE.md              Dev guide for Claude Code sessions
  CONTRIBUTING.md
  Dockerfile
  render.yaml
  LICENSE
  README.md              (you are here)
```

---

## Contributing

Issues and PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
short version.

---

## License and attribution

Application code: [MIT](LICENSE).

Dataset: OpenPowerlifting OpenIPF bulk export, CC0 1.0 Universal. If you
build on this, please credit
[openpowerlifting.org](https://openpowerlifting.org/) and keep a link back
to the source data.

---

## Contact

Built by Matthias Bernhard, UW Nanotech '26 and a raw 83 kg CPU lifter who
wanted to know if his numbers were going to clear the 2027 standard.
