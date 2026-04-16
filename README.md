# CPU Powerlifting Analytics

A web app for Canadian raw powerlifters competing in CPU and IPF-affiliated meets.
Three things in one place:

1. **Cohort progression** — average total change over time, filterable by sex, weight class, equipment, division, age category, and x-axis unit.
2. **QT Squeeze** — four-block view of the percentage of Open lifters who meet CPU qualifying totals across the pre-2025, 2025, and 2027 standards. Includes the forward-looking "what fraction of today's Open lifters already meet the upcoming 2027 standard" metric.
3. **Lifter lookup** — search any Canadian lifter by name, see their full meet trajectory plotted against the qualifying total reference lines for their weight class. Manual entry available for lifters not in the dataset or for projecting hypothetical totals.

Data source: [OpenPowerlifting](https://openpowerlifting.org/), CC0 licensed.

## Stack

- **Backend**: FastAPI + DuckDB over Parquet, Python 3.11+
- **Frontend**: Vite + React + TypeScript + TanStack Query + Recharts + Tailwind v3
- **Data refresh**: GitHub Actions weekly cron downloads the latest OpenIPF bulk CSV, runs preprocess, publishes both parquet files as a `data-latest` GitHub Release
- **Deploy** (planned): Vercel for frontend, Fly.io for backend

## Layout

```
cpu-analytics/
  backend/
    app/
      main.py            FastAPI app + endpoints
      data.py            DuckDB connection (singleton)
      data_loader.py     Downloads parquet from GitHub Release in production
      scope.py           Country=Canada / ParentFederation=IPF defaults
      filters.py         /api/filters enumerated values
      progression.py     Cohort progression analytics
      qt.py              QT coverage + four-block view
      lifters.py         Search + history
      manual.py          Manual meet entry to lifter-history shape
      weight_class.py    Canonical M/F class mapping
    requirements.txt
  data/
    preprocess.py        CSV -> Parquet (one-shot)
    processed/           openipf.parquet, qt_standards.parquet (gitignored)
  frontend/
    src/
      App.tsx            Tab shell
      lib/api.ts         Typed fetch helpers
      tabs/
        Progression.tsx  Cohort progression tab
        QTSqueeze.tsx    QT Squeeze tab
        LifterLookup.tsx Lifter lookup tab (search + manual entry)
    package.json
  .github/workflows/
    refresh-data.yml     Weekly OpenIPF refresh
  LICENSE
  README.md
```

## Local development

### One-time setup

```bash
# Backend
cd cpu-analytics
python -m venv .venv
.venv/Scripts/activate         # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r backend/requirements.txt

# Download a fresh OpenIPF CSV from openpowerlifting.gitlab.io/opl-csv/files/openipf-latest.zip
# Unzip it somewhere, then point preprocess.py at it:
OPENIPF_CSV=/path/to/openipf-YYYY-MM-DD-HASH.csv python data/preprocess.py

# Frontend
cd frontend
npm install
```

### Running locally

```bash
# Terminal 1 — backend
cd cpu-analytics
.venv/Scripts/activate
uvicorn backend.app.main:app --reload

# Terminal 2 — frontend
cd cpu-analytics/frontend
npm run dev
```

Frontend runs at http://localhost:5173 and expects the backend at http://127.0.0.1:8000. Override with `VITE_API_BASE` env var.

## Data refresh

The GitHub Actions workflow at `.github/workflows/refresh-data.yml` runs every Sunday at 06:13 UTC. It downloads the latest OpenIPF bulk CSV, runs preprocess, and publishes the resulting parquet files as a `data-latest` GitHub Release. The production backend reads `OPENIPF_PARQUET_URL` and `QT_PARQUET_URL` env vars to fetch the latest data on container start.

To trigger a refresh manually: GitHub repo → Actions → Refresh OpenIPF data → Run workflow.

## Scope

The site is intentionally limited to Canadian lifters competing in IPF-sanctioned meets (CPU domestic + IPF international). The dataset contains the full OpenIPF dump but the API enforces this scope via default query parameters in `backend/app/scope.py`. Widening scope is a one-line change.

## Deployment

### Backend: Render

The backend is deployed to Render.com via the `Dockerfile` and `render.yaml`
blueprint. The service reads the processed parquet from a rolling
`data-latest` GitHub Release on cold start (env vars
`OPENIPF_PARQUET_URL`, `QT_PARQUET_URL`).

**Health Check Path:** In the Render dashboard go to Settings → Health
Checks and set the path to `/api/health`. This endpoint accepts both
GET and HEAD so Render's own health poll and UptimeRobot's free plan
(HEAD-only) both work.

**Liveness vs readiness:**
- `/api/health` is a fast liveness probe. Returns 200 if the process
  is up, does not hit DuckDB.
- `/api/ready` is a readiness probe. Runs `SELECT 1` against DuckDB to
  confirm the parquet views loaded. Returns 503 if not ready.

### Frontend: Vercel

Auto-deploys on push to `main` from the `frontend/` subdirectory. Set
the env var `VITE_API_BASE` to the Render backend URL.

### Uptime monitoring

UptimeRobot free plan at 5-minute intervals pings `/api/health` with
HEAD. This also keeps the Render free-tier instance warm past the
15-minute idle spindown. A GitHub Actions cron in
`.github/workflows/keepalive.yml` is a belt-and-braces backup in case
UptimeRobot itself is down.

## License

MIT for the application code. The OpenPowerlifting dataset is CC0 1.0 Universal — see [openpowerlifting.org](https://openpowerlifting.org/) for source data and attribution.
