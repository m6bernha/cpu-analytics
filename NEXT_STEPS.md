# Next Steps

Captured 2026-04-16 at the end of the G1-G5 reliability overhaul session.
This is the canonical backlog. Cross items off as they land. When starting a
new Claude session, read this file after `CLAUDE.md`.

## IMMEDIATE manual action (user, no code)

### [ ] Trigger the data-refresh GHA to activate the Canada+IPF parquet shrink

The preprocess now filters to `Country='Canada' AND ParentFederation='IPF'`,
which should shrink the parquet 15-20x. But the published parquet on GitHub
Releases is still the old unfiltered one. Until the next Sunday 06:13 UTC
cron, Render is downloading and serving the old file.

To activate now:
1. Open https://github.com/m6bernha/cpu-analytics/actions
2. Select "Refresh OpenIPF data" workflow
3. Click "Run workflow" -> branch `main` -> "Run workflow"
4. Wait ~2-3 minutes for the workflow to complete
5. Restart the Render service (or wait for the next spin-down/spin-up cycle)
6. Check Render logs for the new `[startup] process RSS: <MB>` line to
   confirm the memory drop

### [ ] Verify UptimeRobot stopped false-alerting

HEAD requests to /api/health now return 200 instead of 405. Log into
UptimeRobot and confirm the monitor is green. If still red, edit the
monitor: verify the URL is `https://cpu-analytics-backend.onrender.com/api/health`
and method is HEAD.

### [ ] Configure Render Health Check Path

Render dashboard -> service -> Settings -> Health Checks -> set path to
`/api/health`. Not yet set (the repo has no render.yaml). Documented in
README.md Deployment section.

## HIGH priority code work

### [ ] Lazy-load `LifterDetail` for ~200 KB bundle saving

`CompareView` lazy-load (commit `19406a4`) only yielded 8 KB because
`LifterDetail` still statically imports Recharts and the Recharts lib lands
in the main chunk. To actually split Recharts out, wrap `LifterDetail` the
same way `CompareView` is wrapped.

Estimated effort: 30 min.

Steps:
1. Extract `LifterDetail` from `frontend/src/tabs/LifterLookup.tsx` into
   `frontend/src/tabs/LifterDetail.tsx` (move the function component and
   its helpers: `EVENT_DESCRIPTION`, `eventLabel`, `eventTitle`, `Era`
   type, `ERA_QT_FIELD`, `ERA_LABEL`).
2. In `LifterLookup.tsx`:
   - `const LifterDetail = lazy(() => import('./LifterDetail'))`
   - wrap `<LifterDetail ... />` in `<Suspense fallback={<LoadingSkeleton chart />}>`
3. Do NOT re-export anything from `LifterDetail` back into `LifterLookup`
   or you'll defeat the split (vite warns `INEFFECTIVE_DYNAMIC_IMPORT`).
4. `npm run build` and verify the main bundle drops by ~150-200 KB and a
   new `LifterDetail-<hash>.js` chunk appears.

### [ ] Complete per-lift filter plumbing (Phase 9 extension)

When the user has `age_category` / `same_class_only` / `max_gap_months` set
and toggles per-lift view, those filters are silently ignored. The UI shows
an amber warning, but the feature is incomplete - a data-correctness gap.

Estimated effort: 1-2 hours.

Steps:
1. Extend `compute_lift_progression` signature in
   `backend/app/progression.py` to accept `age_category`, `max_gap_months`,
   `same_class_only` (same as `compute_progression`).
2. Apply the same filter logic in the function, including the
   age_category baseline recomputation (see
   TestAgeCategoryBaseline tests for the pattern).
3. Update the API endpoint in `main.py` and the frontend
   `fetchLiftProgression` call in `Progression.tsx` to pass them through.
4. Remove the amber warning note in `Progression.tsx` once the filters
   work.
5. Add tests in `backend/tests/test_projection_and_per_lift.py`:
   baseline-recomputation regression for per-lift.

## MEDIUM priority features

### [ ] Bodyweight + Dots progression curves

The parquet has `BodyweightKg` and `Dots` columns. Dots is surfaced in the
meet table but never plotted. BW is not surfaced anywhere.

Estimated effort: 2-3 hours.

Steps:
1. Add a "Metric" dropdown to the Progression filter panel: Total (default)
   | Dots | Bodyweight.
2. In `compute_progression`, parameterize the column that gets averaged
   and diffed (currently hardcoded to TotalKg).
3. For BW, the "progression" concept is different (it's about weight
   cutting / gaining). Consider whether the existing `FirstTotal`-anchored
   diff makes sense or whether absolute value is better.
4. For Dots, the existing pattern works fine (diff from first meet's Dots).

### [ ] Coach view: "Am I on pace for Nationals 2027?"

Individual projection already exists. Add a target-date/target-total mode
that computes expected total on a given date and the gap to the QT.

Estimated effort: 2-3 hours.

Steps:
1. In `LifterDetail`, add a "Target" section: date picker + level toggle
   (Regionals / Nationals) + era toggle.
2. Compute `projected_at_date = slope * days_until_target + intercept`.
3. Compare against the QT for the lifter's class + era.
4. Display: "At this rate, on March 1, 2027 you will be projected to
   total X.X kg (Y.Y below / above Nationals 2027 QT of Z.Z)."

### [ ] Monitor RSS after next cold start

After the parquet-refresh action is triggered, the Render logs will show a
new `[startup] process RSS: <MB>` line (added in G2). Look for this after
the next cold start to quantify the memory improvement.

Expected: current RSS ~200-300 MB drops to ~80-120 MB.

## LOW priority / polish

### [ ] Hypothesis property-based tests for canonical_weight_class

The existing tests check a fixed input set. Hypothesis would catch edge
cases like negative numbers, NaN, infinity, extremely long strings.

Estimated effort: 1 hour.

Install: `pip install hypothesis`
Then add `backend/tests/test_weight_class_properties.py` with a
`@given(st.text())` test that asserts the function never raises.

### [ ] UptimeRobot dashboard verification

Chrome extension blocks dashboard.uptimerobot.com. After the G3 HEAD fix
ships, navigate there manually and confirm the monitor went green.

## Data science depth (aspirational)

### [ ] Per-lifter weighted regression for projection

Currently uses unweighted polyfit for a lifter's projection. Weighting
recent meets more heavily would make the projection more responsive to
current form.

### [ ] Smoothing / moving average overlay

On the individual lifter chart, an optional 3-meet rolling average would
show underlying trend independent of meet-to-meet noise.

### [ ] Percentile rank trajectory

Where did this lifter rank N years ago vs today? Requires recomputing
percentile at each historical meet date. Interesting for tracking
competitive position over time.

### [ ] Optional non-IPF federation support

`scope.py` hardcodes Country=Canada and ParentFederation=IPF. A toggle
to relax these would widen the app to serve non-CPU lifters. Parquet
preprocess would need to be re-scoped or a secondary parquet published.

## Architectural / testing gaps

### [ ] backend/tests for main.py endpoints

No integration tests against the FastAPI app itself. TestClient +
pytest-asyncio would let us assert /api/health responds to HEAD, /api/ready
returns 503 when parquet is broken, etc.

### [ ] Frontend test coverage

There is no frontend test suite at all. Vitest + React Testing Library
would be a low-effort win for the QueryStatus components, useUrlState,
and the event/date formatters.

### [ ] e2e smoke test (Playwright)

A weekly Playwright run that loads the live site, clicks each tab, and
asserts data appears would catch regressions the unit tests can't see
(e.g. cold-start flakes, Vercel deploy breakage).

## Session context for next Claude

- User is Matthias Bernhard, UW Nanotech 4B, raw M SBD CPU powerlifter,
  beginner to programming. See
  `~/.claude/projects/<this>/memory/user_profile.md` for the longer note.
- User prefers spartan writing, no em dashes, no semicolons, no
  rhetorical questions.
- User wants autonomous action, not confirmation loops. See
  `feedback_autonomous.md` in memory.
- The Chrome extension (Claude in Chrome) has a hardcoded domain
  allowlist. Cannot navigate to GitHub, Render dashboard, or
  UptimeRobot dashboard. See `tool_chrome_allowlist.md` in memory.
