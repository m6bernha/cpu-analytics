# Next Steps

Living backlog for the cpu-analytics project. Captured 2026-04-16 during the
Batch 1-3 feedback session. When starting a new Claude session, read this
file after `CLAUDE.md`. Cross items off as they land; add new ones as they
arise.

Ordering is a judgment call between impact and effort.

---

## Session plan -- 2026-04-26 (Arc 1: sweep the deck) -- ALL SHIPPED

Plan-mode v1 audit + execution session. Three commits to main, CI green,
all 11 Arc 1 items shipped. Multi-arc plan locked in
`C:\Users\Matthias\.claude\plans\do-an-audit-as-resilient-sparkle.md`.

1. **Doc rollup** -- SHIPPED `d21953e`. Captured the 4-track wave + Athlete
   Projection BETA recap into CLAUDE.md / NEXT_STEPS.md / README.md /
   docs/ARCHITECTURE.md (147 net insertions). Cleared the working tree
   that had been carrying the 2026-04-23 session's doc edits.
2. **Frontend Arc 1 sweep** -- SHIPPED `a7deadd`. Six items in one commit:
   - **NAV1**: hidden About tab from main nav (route still resolves via
     `?tab=about`)
   - **P3**: removed redundant "Age column vs Division" methodology paragraph
     on Progression
   - **P4**: tightened Progression scope copy. Verified via parquet
     inspection that 69,259 Canadian rows already span CPU + NAPF +
     Commonwealths + IPF Worlds + international IPF affiliates (meet
     countries: Canada, Lithuania, USA, Argentina, Germany). New copy
     accurately describes inclusion of international meets.
   - **AP5**: centered the Athlete Projection InfoPanel grid via `mx-auto`
   - **AP8**: removed the Sean Yen attribution paragraph
   - **SW2**: renamed Sq/Bn/Dl -> Sq/Bp/Dl in LifterDetail meet-table
     column headers
3. **Infra hygiene** -- SHIPPED `0310b9a`. Two items:
   - **INF2**: pinned `ATHLETE_PROJ_TABLES_URL` into `render.yaml`
     Blueprint (was live-only on dashboard since 2026-04-23). Re-provision
     now keeps the var.
   - **INF4**: added `frontend/.env.example` documenting `VITE_API_BASE`
     for next-contributor onboarding.

Plus **MEM1** (visual-QA memory rule) written and indexed in MEMORY.md.

Decisions locked in plan v1:
- **Q1**: keep both projection methods (LL simple regression + AP Engine C);
  surface the difference aesthetically (info icon / method pill, in Arc 3).
- **Q2**: yellow accent -> coral `#FB923C` sitewide. Existing orange uses
  displaced (LL prediction band -> indigo, Progression trend line -> teal,
  Compare-view 6-color non-orange palette).

Still queued (Arcs 2-7 in plan):
- **Arc 2**: Progression sidebar reorder (P1) + checkbox restyle (P2)
- **Arc 3**: sitewide design pass (SW1 color system + AP1 alignment + AP2
  Change-button redesign + AP3 QT reference lines rework + AP4 prediction-
  band display + AP6 horizon-cap + LL2 column wrap)
- **Arc 4 (collapsed into Arc 3)**: Q1 implementation
- **Arc 5**: AP7 Engine D MixedLM wiring
- **Arc 6**: LL3 athlete-card dopamine pass + LL4 live QT integration
- **Arc 7**: INF3 Playwright E2E into CI (parallel-friendly)
- **Arc-X**: SW3 once Matthias's QT-squeeze notes drop

---

## Session plan -- 2026-04-23 (four-track wave + Render artifact activation) -- ALL SHIPPED

Four parallel PRs merged to main in one day, plus the Render
post-merge action via Claude Chrome. Picked over the P7 big-ticket
back-burner because all four were single-session scope and independent
enough to land without blocking each other.

1. **Cohort serialization** (P1 perf) -- SHIPPED `d3e7859` (PR #10).
   New `serialize_tables` / `load_serialized_tables` in
   `backend/app/athlete_projection.py`.
   `preprocess_athlete_projection_tables` in `data/preprocess.py`.
   `ensure_athlete_proj_tables` in `backend/app/data_loader.py`.
   Lifespan in `main.py` tries load-from-disk first, falls back to
   live fit on miss. `.github/workflows/refresh-data.yml` uploads
   the JSON artifact to dated + rolling releases. Schema v1 uses
   `key_bracket` to preserve merged-alias identity. Round-trip test
   `test_round_trip_preserves_merged_alias_identity` locks the
   merged-alias invariant.
   Render env var `ATHLETE_PROJ_TABLES_URL` activated via Claude
   Chrome 2026-04-23 01:43 UTC. Cold-start fit elapsed flipped from
   `elapsed_ms=200698` to `elapsed_ms=2` on instance `b5v21`
   (~100,000x). `/api/ready` 200 confirmed.
2. **Career quartile x-axis** (P6) -- SHIPPED `6e96358` (PR #11).
   `X_AXIS_OPTIONS` += `"Career quartile"` in
   `backend/app/filters.py`. `X_AXIS_COLS` extended in
   `backend/app/progression.py`. Quartile bucketing via pandas
   `groupby.transform` on `DaysFromFirst / career_span`. Projection
   skipped for this axis (normalized units, not time).
3. **LifterLookup Share + URL state** (P5) -- SHIPPED `7fa84e4`
   (PR #12). `ShareButton` extracted to
   `frontend/src/lib/ShareButton.tsx` (clipboard API with textarea
   fallback). URL keys added to LifterLookup: `era`, `view_mode`,
   `range`. `LifterDetail` and `CompareView` accept the state via
   optional props (`prop ?? useState` pattern) so the components
   still work standalone.
4. **Live QT feed on Athlete Projection** (Athlete Projection
   follow-up) -- SHIPPED `3cc8147` (PR #13). Historical era picker
   dropped (user chose option A "replace"). Effective-year picker
   driven by `/api/qt/live/filters`, filtered to years >= 2026
   (CPU Nationals/Regionals only exist from 2026 onward in the live
   feed). Regionals query pinned `region='Western/Central'` until
   CPU publishes non-Western Regionals. URL key `ap_qt_era` ->
   `ap_qt_year`.

Key efficiency observation: the serialize-at-preprocess pattern is
reusable. Any startup fit > 1s on Render should follow the three-
file shape (serialize helper, `ensure_*` loader, `*_URL` env var)
rather than recomputing on every cold boot. Documented in
`~/.claude/projects/<this-project>/memory/project_serialize_at_preprocess_pattern.md`.

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

### Gated items -- status after 2026-04-21 desktop wave

- Issue 1 Recharts display:none: DECIDED + SHIPPED (`cd5e579`, Option B
  per-chart guard).
- Issue 12 Render cold-start: DECIDED, stay on free + keepalive.
- G4 per-chart Recharts guard: SHIPPED via Issue 1 above.
- G5 disclaimer copy pass: SHIPPED 2026-04-21 (commit `61d010c`).
- Branch protection for backend pytest: CLOSED 2026-04-21 via Chrome.
- P0 data-refresh Run #7: VERIFIED green 2026-04-21.

### Athlete Projection (BETA) -- SHIPPED 2026-04-22

Full implementation landed on branch `athlete-projection` in 8 commits:

- **C1** `3713396` add statsmodels + scipy deps.
- **C2** `1a1ac38` Engine C (Huber personal, shrinkage, Kaplan-Meier) + 47 tests.
- **C3** `7bae98f` API endpoint + lifespan precompute + api.ts fetcher.
- **CA1** `fec5a04` ipf_gl_points helper + 23 tests (pivot to GLP-bracket).
- **CA2** `045caed` GLP-bracket cohort stratification + merge fallback +
  two-pass bracket-transition logic (Sean Yen pivot).
- **C4** `651ced6` MVP frontend + resilient division assignment for
  Age-null lifters (~70% of the Canadian parquet).
- **C6** `1d41708` About page + per-tab methodology About links.
- **C5** `d7157a5` gate Engine D toggle until MixedLM wiring ships.
- **C7** `32918ad` offline backtest harness + baseline MAPE artifact.

**Baseline backtest (50-lifter Canada+IPF sample, all ship gates pass):**

| engine       | 3mo  | 6mo  | 12mo | 18mo |
|---|---|---|---|---|
| engine_c     | 3.95 | 3.89 | 7.00 | 5.16 |
| log_linear   | 4.71 | 5.64 | 9.66 | 7.28 |
| gompertz     | 3.17 | 2.80 | 6.27 | 3.61 |

Engine C 6mo < 6% limit. Engine C 12mo < 12% limit. Engine C loses by
<2pp to alternatives at 12mo (Gompertz wins by 0.73pp; log-linear loses
by 2.66pp). No swap required per the plateau-model comparison gate.

Full OpenIPF global run is a separate one-off manual step once the
bulk CSV is available locally. Run with:
```
python data/backtest_projection.py \
  --input data/processed/openipf_global.parquet \
  --output data/backtest_results.json
```

### Athlete Projection follow-ups (post-BETA)

- **Engine D MixedLM wiring** -- the toggle is gated off until the
  real MixedLM precompute + convergence probe lands. Spec in
  backend/app/athlete_projection.py `mixed_effects_projection`
  docstring. Ship criterion: MixedLM converges on >=90% of the
  backtest sample when the probe runs; otherwise keep gated.
- ~~**QT Squeeze About-link**~~ -- SHIPPED 2026-04-22 in commit
  `e8d49c6` after PR #1 merged to main. QTSqueeze.tsx methodology block
  now links to `?tab=about` matching the pattern in Progression,
  LifterLookup, Compare, and Manual entry.
- **Backtest on global OpenIPF** -- populate About page MAPE table
  from a real run on the full global export (~5400 Canada + 500,000+
  global lifters), not the 50-lifter Canadian smoke sample.
- ~~**About page consumes artifact**~~ -- SHIPPED 2026-04-22 in commit
  `9348a00` (PR #2). About.tsx imports
  `frontend/src/data/backtest_results.json` (mirrored from
  `data/backtest_results.json` by `data/backtest_projection.py` on every
  run) and renders the MAPE table + ship-gate status block in place of
  the TBD placeholder. When the global OpenIPF backtest lands, re-run
  the script and the numbers update on next build.
- ~~**Per-lift history in response**~~ -- SHIPPED 2026-04-22 in commit
  `98b57d8` (PR #3). `/api/athlete/{name}/projection` now includes a
  `history` array on each LiftProjection. The frontend plots actual
  squat/bench/deadlift meets as blue scatter dots on the per-lift chart,
  with the projection line joining seamlessly from the last historical
  point.
- ~~**QT reference lines on projection chart**~~ -- SHIPPED 2026-04-22
  in commit `8452835` (PR #4). Optional "Show CPU QT reference lines"
  toggle on the Total view with an era picker (Pre-2025 / 2025 / 2027,
  default 2027). Migration to the live QT feed SHIPPED 2026-04-23
  in commit `3cc8147` (PR #13): historical era picker retired,
  effective-year picker driven by `/api/qt/live/filters` and filtered
  to years >= 2026, Regionals pinned `region='Western/Central'` until
  CPU publishes non-Western Regionals. URL key `ap_qt_era` renamed to
  `ap_qt_year`.
- ~~**Cold-start cost of precompute**~~ -- SHIPPED 2026-04-23
  (PR #10, option (a)). Rather than wait for keepalive to miss, we
  serialized the 231 cohort cells + 7 K-M tables to JSON at
  preprocess time and wired a disk-load path in the FastAPI
  lifespan. Render `ATHLETE_PROJ_TABLES_URL` env var was activated
  2026-04-23 01:43 UTC and the cold-start fit elapsed flipped from
  `elapsed_ms=200698` (~200 s on Render free tier, significantly
  worse than the 27 s measured locally on a faster machine) to
  `elapsed_ms=2`. Option (b) -- lazy first-request fit -- was
  explicitly rejected because it risked a 200 s response for the
  unlucky first-projection user after every cold start. Schema
  version constant `SERIALIZED_TABLES_SCHEMA_VERSION=1` gates
  compatibility; bumping it causes stale artifacts to be rejected
  and the lifespan to fall back to live fit. Merged-alias
  preservation (multiple dict keys pointing at the same cohort cell
  after bracket merging) is locked by
  `test_round_trip_preserves_merged_alias_identity`.

### Athlete Projection / P3 weighting methodology -- SUPERSEDED

Matthias parked this on 2026-04-21 pending academic consultation. On
2026-04-22, coach Sean Yen supplied the GLP-bracket cohort approach
which superseded the original "level-conditioned continuous slope"
plan. Engine C (Bayesian shrinkage) with GLP-bracket cohorts shipped
per the pivot. The original P3 four-methodology menu (A/B/C/D) is
preserved below for reference. Engine D remains deferred (see
follow-ups above).

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

### QT Squeeze overhaul (live-scrape pipeline)

Replacing the manual CSV curation with a scheduled scraper that pulls
current Canadian qualifying totals from powerlifting.ca (and eventually
provincial federations) and auto-refreshes the site when CPU revises
standards every ~2 years. Scope decision 2026-04-21:

* Federal (powerlifting.ca) now, provinces later — one province per
  session as a phased rollout starting with OPA.
* Classic / SBD only. Equipped and Bench Only PDFs are parsed but
  filtered out by the orchestrator. Not negotiable for this project.
* Historical pre-2025 / 2025 values stay in the vendored
  `data/qualifying_totals_canpl.csv` for the "standards tightening
  over time" narrative. The live feed only covers 2026+.
* On detected diff: auto-upload to `data-latest` release, open a
  GitHub issue with the diff, no code commit.
* Weekly cadence, same GHA cron as the OpenIPF refresh.

**Phase 1a -- SHIPPED**

* Parser prototype at `data/scrapers/cpu.py` (`parse_pdf(path)`).
* Shared schema + validation at `data/scrapers/base.py`.
* Orchestrator stub at `data/scrape_qt.py` with CLI: `--once`,
  `--dry-run`, `--regenerate-fixtures`.
* Fixture tests at `backend/tests/test_scrape_qt.py` (11 new tests,
  all passing; total suite 185).
* Committed fixtures: 4 PDFs + 4 `.expected.csv` at
  `backend/tests/fixtures/qt_pdfs/`.
* Dependencies added: `pdfplumber>=0.11`, `requests>=2.32`.

**Phase 1b -- SHIPPED**

* `discover_pdf_urls()` + `download_pdf()` at `data/scrapers/cpu.py`
  rediscover current PDF hrefs from powerlifting.ca landing pages and
  download each to a temp dir. Polite user-agent, retries, 30s timeout.
* `run_once()` at `data/scrape_qt.py` orchestrates scrape → scope-filter
  → validate → sort → diff (against `--existing` CSV) → emit GHA
  outputs. Snapshot written to `data/qt_history/YYYY-MM-DD.csv` on
  detected change.
* `.github/workflows/qt_refresh.yml`: Sundays 06:43 UTC + manual
  dispatch. Downloads existing `qt_current.csv` from `data-latest`
  release, runs scraper, and on change: uploads new CSV, opens an
  issue with the row-level diff, commits the history snapshot. Uses
  the default `GITHUB_TOKEN`, no new secrets.
* 9 new orchestrator tests at `backend/tests/test_scrape_qt.py`
  covering `filter_in_scope`, `sort_rows`, `diff_rows` (no-change / QT
  change / add / remove), `format_diff_summary`, full `run_once` flow
  with monkey-patched fetch (first publish, no-change subsequent run,
  GitHub outputs emission). Total suite: 204 pytest.
* `data/qt_history/.gitkeep` added so the audit-trail directory exists
  in git. `.gitignore` updated to exclude `data/qt_current.csv` and
  `scraper_out/`.

**Phase 1c -- backend SHIPPED, frontend MVP SHIPPED (UX rebuild pending)**

Backend (SHIPPED):

* `backend/app/qt_data_loader.py`: `ensure_qt_current_csv(path)` uses
  local file if present, else downloads from `QT_CURRENT_CSV_URL` env
  var. Validates CSV header against `REQUIRED_QT_CURRENT_COLUMNS` and
  drops the file on mismatch so the next cold start retries.
* `backend/app/data.py`: registers a DuckDB view `qt_current` over the
  CSV when present. Exposes `is_qt_current_available()` so the rest of
  the app can degrade gracefully when the scraper hasn't published yet.
* `backend/app/qt.py`: new `load_live_qt()`, `get_live_qt_filters()`,
  and `compute_live_coverage(sex, level, effective_year, division,
  region, equipment, event)`. Region is tri-state via a `_UNSET`
  sentinel so callers can ask for "null region rows" vs "all regions"
  vs "specific region". Cohort: 24-month window ending March 1 of
  `effective_year`.
* `backend/app/main.py`: new endpoints `/api/qt/live/filters` and
  `/api/qt/live/coverage`. Both return `live_data_available: false`
  gracefully when the view isn't registered. Lifespan warmup logs
  `qt_current=<N> rows` or `qt_current=UNAVAILABLE`.
* 10 new qt.py tests under `TestLoadLiveQt`, `TestGetLiveQtFilters`,
  `TestComputeLiveCoverage`. Total suite: 214 pytest.
* Historical 4-block view (`/api/qt/coverage`, `/api/qt/blocks`, the
  vendored `qualifying_totals_canpl.csv`) is **untouched**. Both data
  paths coexist.

Frontend MVP (SHIPPED):

* `frontend/src/lib/api.ts`: new `fetchQtLiveFilters()` and
  `fetchQtLiveCoverage(params)` with typed request/response shapes.
* `frontend/src/tabs/QtLiveCoveragePanel.tsx` (new): filter panel
  (Sex, Level, Division, Effective Year, Region-conditional-on-2027-
  Regionals) driving a single coverage table (weight class x pct,
  QT kg, N lifters, N meeting). Degrades to a one-line banner when
  `live_data_available: false`.
* `frontend/src/tabs/QTSqueeze.tsx`: imports the new panel and renders
  it above the existing four-block view. The 4-block view is kept
  intact for the historical (pre-2025 / 2025 / 2027-hypothetical)
  narrative.

Frontend UX rebuild -- SHIPPED 2026-04-22 (commit `da4fa24`):

* Four-block layout retired entirely. `QTSqueeze.tsx` shrank from 343
  to 77 lines: header + methodology details + the unified panel.
* `QtLiveCoveragePanel.tsx` is now the only view. Filter row: Sex,
  Level (Nationals/Regionals/Provincials), Division, Effective year +
  conditional Region (2027 Regionals) or Province (Provincials).
* Main bundle dropped 309.82 KB -> 288.14 KB (-22 KB) as Recharts
  BarChart usage left the tab.
* "Data fetched YYYY-MM-DD from powerlifting.ca [and
  ontariopowerlifting.org]" shown in the panel header.

**Phase 2 -- Ontario (OPA) scraper as pilot** -- SHIPPED 2026-04-22

* `data/scrapers/opa.py`: discover_xlsx_url() regexes the Dropbox
  href out of the OPA landing page (html.unescape + dl=1 tweak);
  download_xlsx() streams the file; parse_xlsx() walks the Classic
  sheet only (Equipped and Bench are out of scope).
* Schema extended: `base.py` adds `province` column + `VALID_PROVINCE`
  + `Provincials` level. validate_row enforces that Provincials rows
  have province set and federal rows have province=None.
* Orchestrator runs CPU + OPA back-to-back. OPA failure is
  non-fatal -- federal CSV still publishes. Total in-scope rows:
  696 (580 federal + 116 Ontario).
* Backend `compute_live_coverage` routes Provincials -> province
  filter, federal -> region filter. `/api/qt/live/coverage` accepts
  `province` query param.
* Frontend Level dropdown gains "Provincials"; a Province dropdown
  appears when Provincials is selected. Provinces come from the
  backend's `provinces` filter list so new provinces appear
  automatically as scrapers come online.
* 3 new OPA fixture tests (parser output lock, known-QT spot checks,
  validation). 2 new OPA rows in conftest synthetic fixture to
  exercise the Provincials path in the live-coverage tests.
* Total pytest: 207.

**Phase 3+ -- remaining provinces** (ALL 5 SCRAPERS + ROUTING SHIPPED 2026-04-22)

Provincial-landscape audit 2026-04-22 (parallel Claude chat) + full
build-out in the same session. 10 provinces now routed end-to-end;
scraper modules at ``data/scrapers/<federation>.py`` + test coverage at
``backend/tests/test_scrape_qt.py``. 241 pytest passing.

| Province | Status | Resolution |
|---|---|---|
| Ontario (OPA) | SHIPPED (Phase 2) | Dropbox xlsx scraper |
| British Columbia (BCPA) | SHIPPED (routing) | Frontend routes to CPU Regional Western with banner |
| Alberta (APU) | SHIPPED | Hash-matched manual transcription (data/scrapers/apu.py + apu_transcribed/) |
| Saskatchewan (SPA) | SHIPPED (routing) | Frontend routes to CPU Regional Western with banner |
| Manitoba (MPA) | SHIPPED | PDF scraper (data/scrapers/mpa.py) |
| Quebec (FQD) | SHIPPED | JSON API scraper via Heroku backend (data/scrapers/fqd.py) |
| New Brunswick (NBPL) | SHIPPED (open-entry) | Frontend shows "no QT required" notice |
| Nova Scotia (NSPL) | SHIPPED | Google Sheets gviz CSV scraper (data/scrapers/nspl.py) |
| PEI (PEIPLA) | SHIPPED (open-entry) | Frontend shows "no published standards" notice |
| Newfoundland (NLPA) | SHIPPED | .docx scraper with staleness warning (data/scrapers/nlpa.py) |

**Shipped scrapers (5)**

* **Manitoba** (``data/scrapers/mpa.py``). 3-page PDF from
  ``manitobapowerlifting.ca/wp-content/uploads/.../MPA-Qual-Stds-YYYY.pdf``.
  Reuses pdfplumber. 116 Classic SBD rows. Spot checks locked in
  tests: M 83 Open = 517.5, F 63 Open = 290.
* **Nova Scotia** (``data/scrapers/nspl.py``). Google Sheet via gviz
  CSV export. 232 rows (2026 + 2027). NSPL rounds 0.9 * CPU up to
  2.5 kg after multiplying, so derivation is NOT a substitute for
  scraping -- locked by test (M 59 Open 2026 = 372.5, not 371.25).
* **Newfoundland** (``data/scrapers/nlpa.py``). Google Docs .docx
  export + python-docx. Walks body order to match each of 8 tables
  with its preceding equipment/event label. Logs a staleness warning
  when the source file is older than 2 years (the committed 2022 doc
  trips this; the test asserts the warning fires). 116 Classic SBD
  rows at effective_year=2022.
* **Alberta** (``data/scrapers/apu.py`` +
  ``data/scrapers/apu_transcribed/<year>/``). APU publishes only as
  JPG images, so the scraper uses hash-verified manual transcription
  instead of OCR. Live JPG SHA-256 is matched against a committed
  hash list; on match, the committed CSV rows are emitted; on
  mismatch, ``UntranscribedJpgError`` signals a human to re-
  transcribe. 2026 release transcribed from menclassic_orig.jpg +
  womenclassic_orig.jpg.
* **Quebec** (``data/scrapers/fqd.py``). The FQD React SPA calls a
  Heroku-backed JSON API at
  ``sheltered-inlet-15640.herokuapp.com/api/v1/standards``, so
  Playwright was never required -- the scraper hits the API directly.
  928 records in the payload; the scraper emits only ``level='provs'``
  rows (116 Classic SBD; rest filtered by scope). Effective year
  hardcoded to 2026 because the API omits the field; bump
  ``DEFAULT_EFFECTIVE_YEAR`` when FQD publishes a revision.

**Shipped routing (frontend, QtLiveCoveragePanel.tsx)**

PROVINCE_CATALOGUE in the panel catalogues all 10 provinces with a
mode per entry:

* **Scraped** (AB / MB / ON / QC / NS / NL): hits
  ``/api/qt/live/coverage`` with ``province=<name>``.
* **cpu_regional** (BC / SK): silently rewrites the call to
  ``level=Regionals&region=Western/Central`` and prepends an amber
  banner naming the deferring federation (BCPA / SPA).
* **open_entry** (NB / PE): suppresses the backend call entirely and
  renders a notice card explaining the federation's policy.

**Estimated effort (shipped)**

* Phase 1b: SHIPPED (1 session).
* Phase 1c: SHIPPED (1 session).
* UX rebuild: SHIPPED.
* Phase 2 (OPA): SHIPPED.
* Phase 3 audit: SHIPPED 2026-04-22 (parallel chat).
* Phase 3 all 5 scrapers + routing: SHIPPED 2026-04-22 (this
  session; about 3 hours from plan to PR).

**Open follow-ups (not blocking)**

* ~~OPA Dropbox-link regression~~ -- RESOLVED 2026-04-22. Re-verified end
  to end against the live OPA landing page: ``discover_xlsx_url`` finds
  the Dropbox href, ``download_xlsx`` streams the workbook, and
  ``parse_xlsx`` emits 116 Classic SBD rows. Full orchestrator run
  produces 1392 in-scope rows across CPU + 6 provincial scrapers. The
  earlier graceful-degrade warning was likely a transient OPA page
  update that has since re-stabilised.
* FQD Quebec ``DEFAULT_EFFECTIVE_YEAR`` currently hardcoded to 2026;
  bump when FQD publishes a revision tied to the CPU calendar.
* Alberta transcribed releases under ``apu_transcribed/`` grow over
  time. When APU publishes new images, re-hash + re-transcribe.

**Operational notes**

* powerlifting.ca uses Wix CMS. PDF URLs rotate on every revision
  (`_files/ugd/<segment>/<hash>.pdf`), so the scraper must rediscover
  URLs from the landing page every run. Do not hardcode PDF URLs.
* CPU landing pages to crawl: `/qualifying-standards/` (2026 current)
  and `/2027qualifications` (2027 effective Jan 1, 2027).
* Parser uses pdfplumber `extract_tables()` not text heuristics. Table
  grid is 8 columns (weight class + 7 age divisions).
* Fixture tests lock parser output row-for-row. If CPU restructures the
  PDFs, tests fail before a bad CSV reaches production. To refresh
  fixtures after an intentional parser change, run
  `.venv/Scripts/python -m data.scrape_qt --regenerate-fixtures` and
  review the diff before committing.

### Manual entry: individual lift inputs — SHIPPED

Commit `43c467b`. `total_kg` is optional in `manual.py`; a new
`_reconcile_total_and_lifts` model validator enforces "total only OR all
three lifts", auto-sums when total omitted, rejects mismatches (tol
0.01 kg). Nine test cases in TestTotalAndLiftsReconciliation. Frontend
ManualFormRow adds squat/bench/deadlift inputs on desktop table and
mobile card; total placeholder becomes auto from S/B/D; partial-lift
warning banner blocks submit.

### ~~Athlete Projection (BETA) tab -- full implementation~~ -- SHIPPED (BETA)

BETA tab shipped 2026-04-22 across 10 commits on the `athlete-projection`
branch, merged to main as `2268c45`. Per-lift Bayesian shrinkage
(Engine C) with 2D (age division × IPF-GL bracket) cohort stratification,
Kaplan-Meier dropout-adjusted prediction intervals, two-pass
bracket-transition projection, outlier flag, and a matching About page
with full methodology. Backtest harness at `data/backtest_projection.py`
ships with a 50-lifter Canada+IPF baseline (all three ship gates pass).

The original spec below is preserved for historical reference. The
"personal vs. cohort weight" slider was replaced by a Bayesian shrinkage
posterior that picks the weight per-lifter based on sample size and
residual variance -- see `athlete_projection.py`:
`shrinkage_projection` and the About tab's methodology block.

Remaining follow-ups tracked in the "Follow-ups from the Athlete
Projection BETA" block near the top of this file (Engine D MixedLM
wiring, global-OpenIPF backtest, About-page artifact rendering, per-lift
history arrays, cold-start cost measurement).

Historical spec (superseded):

1. ~~Pick a lifter (search) OR use "current manual entry".~~ Lifter
   search + projection shipped.
2. ~~Pick a target date.~~ Horizon-months parameter (1-24).
3. ~~Pick a target QT.~~ Deferred to a future QT-overlay follow-up;
   current BETA shows the projection only.
4. ~~Output: predicted total + confidence interval + kg-gap to QT.~~
   Shipped minus the QT gap (see #3).
5. ~~Slider between personal and cohort weights.~~ Replaced by
   Bayesian shrinkage posterior.

### ~~Coach "on pace for Nationals 2027" widget~~ -- SUPERSEDED

Folded into the shipped BETA. The "on pace" view is now the per-lift
projection chart with QT reference lines landing in a later follow-up.
Use the Athlete Projection tab as the UX home for this workflow.

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

## P4 -- Transparency / methodology writing -- SHIPPED

Commit `61d010c` landed 2026-04-21 for the base tabs. The Athlete
Projection BETA tab got its own MethodologyBlock inside
`AthleteProjection.tsx` in commit `651ced6` (2026-04-22). The QT Squeeze
About-link follow-up shipped in `e8d49c6` (2026-04-22). Every
user-facing tab now carries a collapsed `<details>` block styled
consistently, and every one of them links to the About page for full
methodology detail.

Original content sketch (now implemented):

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

## P7 -- Back burner / big-bet ideas (park until Matthias is present)

These are multi-session features with significant scope and design
decisions that should only be picked up when Matthias is present to
steer. Captured here so they are not lost.

### ML-based projection engine (replaces or augments Engine C/D)

Pitch: approach projections as a supervised ML problem instead of a
statistical shrinkage model. Train on the full historical parquet with
an 80/20 split where the most recent competitions are the held-out
validation set. Features would be the same variables Engine C uses
(personal slope, cohort slope, GLP bracket, age division, KM survival,
meets-contested) plus a larger feature set the ML model can exploit
(recent-form windows, rest intervals, bodyweight trajectory, event
participation pattern).

Decisions needed before starting:
- Model family: gradient-boosted trees (XGBoost/LightGBM) vs deep
  learning vs simple regularised regression. GBTs are the natural
  default -- tabular data, non-linear, explainable via SHAP, trains
  fast enough to rerun per data refresh.
- Target variable: does the model predict Total at horizon, or the
  delta from current level? Delta is usually easier to fit and reads
  like Engine C's output.
- Validation strategy: most-recent-competitions as holdout is a
  time-aware split. Must confirm there is no leakage (a lifter's Dec
  2024 meet cannot be used to predict their Jun 2024 meet).
- Serving: bake the model artifact into the backend at preprocess
  time (like the cohort cells), or move inference to a separate
  service. The 27 s precompute cost is already on the edge; a
  fitted model loaded from disk is cheap.
- How to communicate uncertainty. MAPE is the current metric;
  ML-model PIs typically come from quantile regression or conformal
  prediction.

Data scope for this to meaningfully beat Engine C: must expand beyond
Canada+IPF to North America plus Europe (same expansion as the Wrapped
feature below). The Canadian pool alone is too small for a model that
can learn subtle plateau patterns.

Ship criterion: ML engine beats Engine C by >2 pp MAPE at the 12 mo
horizon on held-out competitions. Otherwise stay on Engine C.

### Spotify-Wrapped-for-lifters (viral career retrospective)

Pitch: a shareable year-end (or career-end) summary card for each
lifter, designed to promote organic sharing among the powerlifting
community. Does not add analytical functionality -- it is a
presentation layer on data the site already has. Goal is laymen-level
virality, the kind that gets posted to Instagram stories.

Card contents (stacked slides, single-page layout):
- Total kilos lifted across a career (sum of every meet's Total).
- Meet count and competition cadence.
- Best-ever lift at S, B, D with the meet + date.
- Weight-class migrations with a timeline chip for each transition.
- Career milestones: first 300, first 400, first Nationals-qualifying
  total, first Regionals, first meet, PR streaks.
- Year-over-year progression curve.
- Age-division transitions (Sub-Jr -> Jr -> Open -> M1 ...).
- A top-of-cohort percentile summary for their most recent year.
- Shareable image export (PNG) for Instagram-story aspect ratios.

Decisions needed before starting:
- Does the share export render server-side (Playwright screenshot of
  a dedicated `/wrapped/<name>` route) or client-side (html2canvas
  over the visible slide)? Server-side is more robust but adds a
  build dependency; client-side is faster to ship.
- Is this a standalone tab or a drawer/modal inside Lifter Lookup?
  Probably a standalone tab so the share URL is short.
- Privacy: the parquet already contains names; no PII beyond what
  OpenPowerlifting publishes. Still worth a note that anyone can
  generate a card for any public lifter.
- Evergreen vs yearly cadence. Spotify Wrapped is annual; a lifter
  retrospective is probably more useful on-demand (anyone can view
  their own card any time) with optional "year in review" framing
  in December/January.

Data scope: must expand beyond Canada+IPF. A wrapped card only has
shareable value if North American and European lifters are covered.
The current `scope.py` hardcode to `Country=Canada AND
ParentFederation=IPF` would need to become a soft filter that the
Wrapped feature bypasses (or the preprocess pipeline adds a second
parquet with the wider scope). This expansion is itself a multi-session
decision -- 5.4k Canada+IPF lifters vs ~500k global lifters changes
memory, cold-start, and the feel of every other tab.

Decisions needed before starting:
- Which federations to include. IPF globally, or wider (USAPL, USPA,
  GPC, WPC, federation-neutral)? Probably IPF globally for Wrapped v1,
  expand later.
- Storage cost. 500k lifters x average 3 meets is ~1.5M rows; still
  fits comfortably in parquet but push Render's 512 MB harder than
  the current 5.4k.
- Scope toggle semantics. Does `Progression` tab stay Canada-only by
  default, or does the expansion become the new default? Affects every
  cohort computation.

### Scope expansion to North America + Europe

Prerequisite for both ideas above. Currently
`backend/app/scope.py` locks the parquet view to
`Country=Canada AND ParentFederation=IPF`. The expansion options:

1. Widen the preprocess filter to include all IPF-sanctioned meets
   globally (keeps a single parquet + single scope assumption).
2. Keep the Canada+IPF default for the existing tabs and publish a
   second `openipf_global.parquet` for Wrapped + ML-projection
   features. Per-tab scope toggle.
3. Make scope a first-class runtime filter on every query, with a
   user-facing toggle. Most flexible, highest refactor cost.

Decisions needed before starting:
- How many lifters / rows are acceptable at the Render 512 MB ceiling.
  Global IPF is ~500k lifters, which is ~100x current.
- Which tabs see the wider data by default. CPU / Canadian scope is
  the current branding ("cpu-analytics"); widening the default changes
  the product identity.
- Whether to rename the product. "cpu-analytics" ties the project to
  CPU specifically; a wider scope probably needs a different name.

---

## Chrome audit 2026-04-17 -- backlog

External exploration of the live site + Vercel + Render + GitHub surfaced 15
distinct issues. The UX triage chat shipped a safe batch in its own session
(Issues 6, 8, 9, 10, 7-partial, 13-verify, 15-verify). Remaining items gated
below.

### Active triage table

| # | Issue | Severity | Effort | Owner | Gate | Status |
|---|---|---|---|---|---|---|
| 1 | Recharts -1x-1 warnings from display:none inactive tabs in App.tsx | high | L per-chart | G4 parallel chat | closed | SHIPPED `cd5e579` 2026-04-21. isActive prop plumbed from App.tsx through each tab, gates ResponsiveContainer subtree only. Tab components stay mounted (scroll + dropdown + search-query state preserved). Bundle delta +219 B. Zero width(-1) height(-1) warnings on tab switches. |
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
5. **G5 disclaimer copy pass** — SHIPPED 2026-04-21 (commit `61d010c`)
   for the base tabs and 2026-04-22 for the Athlete Projection BETA
   (commit `651ced6`) and the QT Squeeze About-link (commit `e8d49c6`).
   Closes P4. Methodology/caveat `<details>` blocks on every tab now
   link to the About page (`?tab=about`) for full methodology.

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
