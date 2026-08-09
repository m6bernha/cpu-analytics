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
      |   Endpoints: see the API surface table below               |
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

### API surface

Every route in `backend/app/main.py`. Regenerate this list with
`grep -nE '@app\.(get|post|api_route)' backend/app/main.py` if it looks stale.

| Method | Path | Purpose |
|---|---|---|
| GET/HEAD | `/api/health` | Liveness. Does not touch DuckDB. HEAD for UptimeRobot. |
| GET/HEAD | `/api/ready` | Readiness. Runs `SELECT 1`; 503 if the views are broken. |
| GET | `/api/meta/freshness` | Newest meet date + row count, for the staleness badge. |
| GET | `/api/filters` | Enumerated dropdown values. `lru_cache`d. |
| GET | `/api/cohort/progression` | Cohort aggregation with trendline and projection. |
| GET | `/api/cohort/lift_progression` | Per-lift (S/B/D) cohort view. SBD-only in practice. |
| GET | `/api/rankings` | Leaderboard, 24-month active window, paginated. Raw SBD only. |
| GET | `/api/rankings/percentiles` | Per-sex GLP percentile curve (101 floats). |
| GET | `/api/lifters/search` | Name search. Wildcards escaped, capped at 200. |
| GET | `/api/lifters/{name}/history` | Full meet history for one lifter. |
| GET | `/api/athlete/{name}/projection` | Per-lift forecast, Engine C or D, with PIs. |
| GET | `/api/athlete/projection-engines` | Which engines are available (Engine D gate). |
| GET | `/api/meet` | One meet's results as a record, grouped and never ranked. |
| GET | `/api/qt/standards` | Historical QT table (pre-2025 / 2025). |
| GET | `/api/qt/coverage` | Historical QT coverage. |
| GET | `/api/qt/live/filters` | Live QT feed filter lists. Degrades if unavailable. |
| GET | `/api/qt/live/coverage` | Live QT coverage, federal + provincial. |
| POST | `/api/manual/trajectory` | Validated manual entry. Rate limited 30/min per IP. |
| POST | `/api/scout/report` | Scouting report fan-out. Rate limited 10/min per IP. |

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
2. **Python `lru_cache`** on `get_filters`. Cache entries are small, and
   the result only changes on parquet refresh (which triggers a Render
   container restart). `maxsize` is intentionally small to cap memory.

### Lifespan warmup

The FastAPI `lifespan` hook does three things before the app accepts
traffic:

1. Downloads the parquet files if they aren't on local disk
   (`data_loader.py`). Includes `athlete_projection_tables.json` (since
   2026-04-23) so the Athlete Projection 231-cell cohort + 7 K-M
   tables load from disk in ~2 ms instead of refitting in ~200 s on
   Render free tier.
2. Tries `load_serialized_tables` for the Athlete Projection artifact.
   On miss (no env var, download failure, schema mismatch) falls back
   to a live `precompute_tables` fit using the in-memory DuckDB view.
   `SERIALIZED_TABLES_SCHEMA_VERSION` rejects stale artifacts after a
   breaking schema change.
3. Runs `SELECT COUNT(*)` against both parquet views to force DuckDB
   to open the parquet files rather than defer the work to the first
   real request.

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
| `tab` | App shell | `progression`, `projection`, `qt`, `lookup`, `scout`, `about` (all six are in the nav as of 2026-07-01; `scout` was relaunched with a sex filter after its 2026-06-19 pull, `about` went public alongside it) |
| `sex`, `weight_class`, `equipment`, `tested`, `event`, `division`, `age_category`, `x_axis` | Progression filters | `M`, `83`, `Raw`, `Yes`, `SBD`, `Open`, `All`, `Years`, `Career quartile`, `Bodyweight bucket` |
| `mode` | Lifter Lookup | `search`, `compare`, `manual` |
| `lifter` | Lifter Lookup search | `Matthias Bernhard` |
| `lifters` | Lifter Lookup compare | `Matthias Bernhard,Alex Mardell` |
| `era`, `view_mode`, `range` | Lifter Lookup | `2025`, `total`, `all` |
| `ap_name`, `ap_horizon`, `ap_qt_year` | Athlete Projection | `Matthias Bernhard`, `12`, `2027` |

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

Both `CompareView` and `LifterDetail` are lazy-loaded inside
`LifterLookup.tsx` via dynamic imports. They ship as 11 KB and 18 KB
chunks respectively. Recharts is a shared 357 KB chunk that only loads
when either view opens. Main bundle dropped from 663 KB to ~295 KB
(-55%) after the LifterDetail split shipped 2026-04-20. A `ShareButton`
shared component at `frontend/src/lib/ShareButton.tsx` (added
2026-04-23) lets any URL-backed tab expose a one-click shareable link.

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

## Discoverability

### Sitemaps

`data/generate_sitemap.py` reads the parquet and writes four files into
`frontend/public/`, which Vercel serves as ordinary static assets:

| File | Contents |
|---|---|
| `sitemap.xml` | The index. Keeps this filename so `robots.txt` and anything search engines already have on file stay valid. |
| `sitemap-core.xml` | The seven tab views. |
| `sitemap-athletes.xml` | One URL per lifter, ~21k, ordered by most recent meet. |
| `sitemap-meets.xml` | One URL per (meet, date), ~2.8k. |

Two decisions worth keeping:

- **Static files, not a backend endpoint.** Render's free tier can take
  ~50 s to wake and a crawler gives up in 5-10 s, so serving sitemaps from
  the API would mean the crawl fails exactly when the site is idle, which
  is most of the time. The cost is that sitemaps refresh weekly with the
  data rather than on demand.
- **Encoding must match `route.ts` byte for byte.** The slug is the
  URL-encoded exact OpenIPF name. A mismatch does not 404 (the SPA rewrite
  catches every `/athlete/*`), it renders "lifter not found" while still
  returning 200, so only `backend/tests/test_generate_sitemap.py` catches
  it. Do not change `encode_segment` without running those tests.

The weekly refresh regenerates the sitemaps and opens an auto-merging PR
rather than pushing to `main`, because `main` requires status checks that a
freshly pushed commit cannot have.

### Per-page metadata and structured data

`src/lib/ogMeta.ts` is a pure string transform (unit-testable without an
edge runtime) that the middleware runs over the fetched SPA shell. It owns
three things per page:

1. **`<meta name="description">`** — the SEARCH SNIPPET. Distinct from
   `og:description`, which only drives social previews. Until 2026-08-09
   this tag was not owned, so all ~23k athlete and meet pages inherited
   index.html's single site-wide sentence and competed for the same snippet.
2. **`og:*` / `twitter:*` / `<title>` / canonical** — replaced, never
   appended, so there is exactly one of each.
3. **JSON-LD** — `ProfilePage` wrapping a `Person` for athletes,
   `SportsEvent` for meets.

The JSON-LD deliberately asserts only what the dataset knows. Meets carry
no `location` (preprocess drops `MeetTown`/`MeetState`, so the town is
genuinely unknown) and no `eventStatus` (these are completed meets, so
`EventScheduled` would be false). Omitting `location` costs Google Event
rich results; inventing a venue would be a policy violation and a lie, so
the trade is not close.

Values are serialized with `<` escaped to `<` so a meet name
containing `</script>` cannot close the block and become markup. Meet names
are federation-entered free text, so that is a real input.

### Analytics

Vercel Web Analytics, mounted in `main.tsx`. Cookieless, so no consent
banner. Custom events go through `src/lib/analytics.ts`, which exists so
the event vocabulary is a type rather than a set of scattered string
literals. Two rules hold there: no user-typed or identifying values as
properties, and bucket unbounded numbers before sending. Athlete-page
popularity comes from ordinary pageviews of the real `/athlete/*` paths;
the custom events cover behaviour the URL cannot show, starting with which
tab is open, since tabs live in the query string.

## Testing

- **Backend**: pytest + Hypothesis property tests. 406 tests passing,
  1 skipped. Covers progression aggregation, rankings (leaderboard +
  GLP percentile curves), lifter search, PR detection, manual-entry
  validation, QT coverage (federal + 6 provincial scrapers), athlete
  projection (Engine C + Engine D), scout report generation, per-IP
  rate limiting, sitemap URL encoding, concurrency (32 parallel threads
  against DuckDB), and weight-class canonicalization.
- **Frontend**: Vite production build + strict TypeScript serve as the
  primary gate. 107 Vitest unit tests (ogMeta + route + percentile +
  useUrlState + MethodPill + Banner + meetTier + AthleteCard + Scout
  roster/override helpers) and 6 Playwright E2E smoke tests, all
  running in CI.
- **CI**: `.github/workflows/ci.yml` runs all three jobs on every push
  and PR in parallel, target wall-clock under 3 minutes. Branch
  protection on `main` requires all three: `Frontend (tsc + build)`,
  `Backend (pytest)`, and `E2E (Playwright smoke)`.

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
