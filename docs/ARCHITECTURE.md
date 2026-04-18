# Architecture

This doc describes how the pieces fit together. The
[README](../README.md) is the one-page overview; this file is for
readers who want the depth.

## Goals

1. **Fast cold start on free hosting.** Render's free tier spins down
   after 15 minutes of idle traffic. A cold boot must produce a usable
   app in under a minute without paying for warm instances.
2. **Weekly-fresh data.** OpenPowerlifting publishes a bulk CSV. The app
   must reflect that without manual intervention.
3. **Predictable scope.** Queries must always be Canada + IPF. A
   refactor must not accidentally widen the scope.
4. **Sharable views.** Every meaningful UI state must be URL-encodable
   so a lifter can send a teammate a link to a specific cohort chart.

## System diagram

```
                                 weekly cron (Sundays 06:13 UTC)
                                 |
      +--------------------------v---------------------------------+
      | GitHub Actions: .github/workflows/refresh-data.yml         |
      |                                                            |
      |   1. curl openipf-latest.zip from openpowerlifting.gitlab  |
      |   2. unzip + run data/preprocess.py                        |
      |      - filter Country=Canada, ParentFederation=IPF         |
      |      - write openipf.parquet + qt_standards.parquet        |
      |   3. gh release upload data-latest openipf.parquet ...     |
      +--------------------------+---------------------------------+
                                 |
                                 v
                   +--------------+---------------+
                   |  GitHub Release: data-latest |
                   |  - openipf.parquet  (~28 MB) |
                   |  - qt_standards.parquet      |
                   +--------------+---------------+
                                  |
        cold-boot HTTP GET of the two release assets
                                  |
      +---------------------------v--------------------------------+
      | Render.com (free tier, Docker)                             |
      |                                                            |
      |   FastAPI (backend/app/main.py)                            |
      |    - lifespan hook downloads parquet, warms DuckDB views   |
      |    - per-request DuckDB cursor (thread-safe)               |
      |    - GZip + Cache-Control middleware                       |
      |                                                            |
      |   Endpoints:                                               |
      |    GET  /api/health                liveness (no DuckDB)    |
      |    GET  /api/ready                 readiness (SELECT 1)    |
      |    GET  /api/filters               enumerated dropdowns    |
      |    GET  /api/progression           cohort aggregation      |
      |    GET  /api/progression/per-lift  per-lift cohort view    |
      |    GET  /api/qt/blocks             4-block QT coverage     |
      |    GET  /api/qt/coverage           single-cut coverage     |
      |    GET  /api/qt/standards          QT table data           |
      |    GET  /api/lifter/search         name search             |
      |    GET  /api/lifter/history        meet history            |
      |    POST /api/lifter/manual         validated manual entry  |
      +---------------------------+--------------------------------+
                                  |
                      HTTPS (CORS + VITE_API_BASE)
                                  |
      +---------------------------v--------------------------------+
      | Vercel (Hobby)                                             |
      |                                                            |
      |   Vite + React 19 + TypeScript SPA                         |
      |    - TanStack Query (retry 3x, staleTime 5-10 min)         |
      |    - Recharts (dark theme, fixed-height ResponsiveContainer|
      |    - Tailwind v3                                           |
      |    - useUrlState: URL = source of truth for shareable state|
      +------------------------------------------------------------+
```

## Backend

### DuckDB over Parquet

DuckDB is embedded: no external database, no connection pool, no
migrations. The backend holds one in-memory DuckDB connection and
registers two parquet files as views at startup:

```sql
CREATE OR REPLACE VIEW openipf       AS SELECT * FROM read_parquet('openipf.parquet');
CREATE OR REPLACE VIEW qt_standards  AS SELECT * FROM read_parquet('qt_standards.parquet');
```

Every request acquires its own cursor via `get_cursor()` (a FastAPI
dependency-like pattern, not a dependency). Cursors share the base
connection but expose independent execution state. This was a regression
fix: DuckDB's parent `.execute()` is not safe under concurrent request
load, which surfaced as "No open result set" crashes.

### Scope enforcement

`backend/app/scope.py` is the single source of truth:

```python
DEFAULT_COUNTRY = "Canada"
DEFAULT_PARENT_FEDERATION = "IPF"
```

Every SQL query joins on or filters by these. The parquet itself is also
pre-filtered at preprocess time, so even an API regression that dropped
the filter would still serve only Canadian IPF data. Belt and
suspenders.

### Caching

Two layers:

1. **DuckDB view caching.** Parquet reads are column-pruned and
   predicate-pushed, so a "give me all M 83kg SBD Open meets" query
   scans only the relevant columns.
2. **Python `lru_cache`** on `compute_blocks` and `get_filters`. Cache
   entries are small, and results only change on parquet refresh (which
   triggers a Render container restart). `maxsize` is intentionally
   small (1-8) to cap memory.

### Lifespan warmup

The FastAPI `lifespan` hook does two things before the app accepts
traffic:

1. Downloads the parquet files if they aren't on local disk
   (`data_loader.py`).
2. Runs `SELECT COUNT(*)` against both views to force DuckDB to open the
   parquet files rather than defer the work to the first real request.

If either view returns 0 rows (corrupt parquet), it deletes the local
files so the next cold boot re-downloads rather than serving broken
data indefinitely.

### Request timing middleware

Every request logs `[req] METHOD /path STATUS Xms`. Crashes log
`CRASH in Xms`. Visible in Render logs for debugging production timing
regressions without setting up a metrics stack.

### DuckDB exception handler

A dedicated `@app.exception_handler(duckdb.Error)` catches DuckDB crashes,
logs the request path + exception + stack trace, and returns a clean
503 JSON `{"error": "database_error"}` to the client. Means future data
issues surface with "which endpoint triggered it" context.

## Frontend

### URL as source of truth

Every shareable UI state lives in `window.location.search` via the
`useUrlState` hook. Keys are omitted from the URL when they equal their
default, so a pristine page has a clean URL. Multiple `useUrlState`
instances coexist safely on the same page, with a dev-only warning if
two components try to own the same key.

Registered keys (as of 2026-04):

| Key | Scope | Example |
|---|---|---|
| `tab` | App shell | `progression`, `projection`, `qt`, `lookup` |
| `sex`, `weight_class`, `equipment`, `tested`, `event`, `division`, `age_category`, `x_axis` | Progression filters | `M`, `83`, `Raw`, `Yes`, `SBD`, `Open`, `All`, `Years` |
| `mode` | Lifter Lookup | `search`, `compare`, `manual` |
| `lifter` | Lifter Lookup search | `Matthias Bernhard` |
| `lifters` | Lifter Lookup compare | `Matthias Bernhard,Alex Mardell` |

Example permalinks:
- `/?tab=progression&weight_class=83&x_axis=Months`
- `/?tab=lookup&lifter=Matthias%20Bernhard`

### TanStack Query defaults

Cold-start friendly: `retry: 3`, exponential backoff up to 30 s,
`staleTime: 5 min`, `refetchOnWindowFocus: false`. Individual queries
override where relevant (e.g., the filter enumeration uses 10 min
`staleTime` since it only changes on parquet refresh).

The `fetchFilters` fetcher additionally validates that required arrays
are non-empty and throws on partial data, so TanStack Query's retry
kicks in for partial cold-start responses too. This was a real
regression: an empty-equipment array made it through without this
check.

### Error and loading states

`lib/QueryStatus.tsx` standardizes two components used by every query:

- `QueryErrorCard` shows the HTTP status, a Retry button, and a short
  cold-start explanation so users don't stare at a blank chart when
  Render is warming up.
- `LoadingSkeleton` renders a neutral placeholder.

Each tab is wrapped in an `ErrorBoundary` so a render-phase crash in
one tab shows a recoverable error panel without blanking the others.

### Code splitting

`CompareView` is lazy-loaded inside `LifterLookup.tsx` via a dynamic
import. It ships as its own ~8 KB chunk. Recharts is still
static-imported in `LifterDetail`; lazy-loading that view is a tracked
item in `NEXT_STEPS.md`.

### Charts

Every chart:
- `ResponsiveContainer` with a fixed pixel height so the aspect ratio is
  readable on both mobile and desktop.
- `Legend` at `verticalAlign="top"` so it doesn't overlap the x-axis
  label.
- Dark theme: axis lines `#3f3f46`, primary blue `#569cd6`, orange
  `#ce9178`, teal `#4ec9b0`, purple `#c586c0`.
- No chart is rendered inside a `display:none` parent (Recharts warns
  with `width=-1 height=-1` in that case).

## Data pipeline

See [DATA.md](DATA.md) for the full data-flow, schema, and QT-standard
details.

## Testing

- **Backend**: pytest + Hypothesis property tests. 158 tests passing.
  Covers progression aggregation, lifter search, PR detection, manual-
  entry validation, QT coverage, concurrency (32 parallel threads
  against DuckDB), and weight-class canonicalization.
- **Frontend**: Vite production build + strict TypeScript serve as the
  gate. No runtime test suite yet (tracked in `NEXT_STEPS.md`).
- **CI**: `.github/workflows/ci.yml` runs both on every push and PR in
  parallel, target wall-clock under 3 minutes. Branch protection on
  `main` requires the frontend check to pass.

## Deploy topology

| Concern | Solution |
|---|---|
| Frontend hosting | Vercel Hobby, free |
| Backend hosting | Render.com free tier, 15-min idle spindown |
| Cold-start mitigation | UptimeRobot HEAD ping every 5 min + GHA cron `.github/workflows/keepalive.yml` |
| TLS | Both hosts auto-provision |
| CI | GitHub Actions |
| Data pipeline | GitHub Actions weekly cron + GitHub Release as artifact store |
| Secrets | Render and Vercel env vars; no secrets in the repo |

Total cost: $0 / month. The trade-off is the 20-50 s cold start, which
the keepalive ping masks during peak hours.

## Known limitations

- **Age column is ~70% NULL in OpenIPF.** Any age_category filter
  silently drops rows. The Progression tab shows a hint about this.
- **Division is free-text.** `Division='Open'` works for CPU
  specifically (empirically verified). Not federation-portable.
- **TotalKg can be null** (DQ / bombed / bench-only meets). All
  arithmetic guards against null.
- **Men <58 kg drop** in QT views. No CPU QT standard exists for that
  range.
- **Weight-class canonicalization is aggregate-correct, edge-case
  imperfect.** Some historical 1-kg-off variants collapse into modern
  classes. Fine for cohort stats, wrong for specific individuals in
  those edge cases.

See [NEXT_STEPS.md](../NEXT_STEPS.md) at repo root for the living
backlog.
