# Engine D — Visual QA checklist (Arc 6)

**Purpose:** Verify Engine D (MixedLM random-intercept-only, gate at 0.70,
live full-scale convergence 100%) renders correctly on the production site
across three lifters that exercise different code paths. Pending since
2026-05-01.

**Live site:** https://cpu-analytics.vercel.app

**How to use:** Open each lifter URL below, walk the 10-row checklist, mark
each row pass / fail with a one-line note. Anything failing becomes a
follow-up entry in `NEXT_STEPS.md` under P1.

---

## Lifters

Discovered 2026-05-19 by hitting `/api/athlete/{name}/projection?horizon_months=12&engine=mixed_effects`
on the live backend. Each picks a different code path through Engine D.

### Lifter A — clean Engine D, rich personal history, Open M

**Name:** Mark Tobias
**URL:** https://cpu-analytics.vercel.app/?tab=projection&ap_name=Mark%20Tobias&ap_horizon=12

| Path signal | Value (2026-05-19) |
|---|---|
| Division | Open |
| GLP bracket | 105–110 |
| Cell sample (n_lifters) | 22 |
| Personal meets (S/B/D) | 20 / 20 / 20 |
| `engine_d_partial` | False |
| Fallback lifts | none |
| KM sample | 5,237 |

**Expected:** Engine D toggle visible. Switching C → D shifts the projected
line (cohort drift differs from Engine C's shrinkage cohort slope). No
fallback banners. PI band scales with horizon.

### Lifter B — whole-cell fallback to Engine C, Master with rich personal data

**Name:** Bruce Markham
**URL:** https://cpu-analytics.vercel.app/?tab=projection&ap_name=Bruce%20Markham&ap_horizon=12

| Path signal | Value (2026-05-19) |
|---|---|
| Division | M2 |
| GLP bracket | 90–95 |
| Cell sample (n_lifters) | 3 (below the n>=20 / n_meets>=60 floor) |
| Personal meets (S/B/D) | 21 / 22 / 21 |
| `engine_d_partial` | False (all fall back together) |
| Fallback lifts | squat, bench, deadlift |
| KM sample | varies |

**Expected:** Engine D toggle visible. Switching C → D produces a banner
or `engine_d_note` reading "All lifts fell back to Engine C: no converged
MixedLM cell for this lifter's (division, bracket)." Numeric projection
should be identical to Engine C since fallback uses C's cell.

### Lifter C — Junior, sparse personal data, clean Engine D

**Name:** Matthias Bernhard
**URL:** https://cpu-analytics.vercel.app/?tab=projection&ap_name=Matthias%20Bernhard&ap_horizon=12

| Path signal | Value (2026-05-19) |
|---|---|
| Division | Jr |
| GLP bracket | 70–80 |
| Cell sample (n_lifters) | 154 |
| Personal meets (S/B/D) | 3 / 3 / 3 |
| `engine_d_partial` | False |
| `small_n_warning` | True |
| `horizon_capped` | True (horizon trimmed for sparse history) |
| Fallback lifts | none |
| KM sample | 3,282 |

**Expected:** Engine D toggle visible. Projection shows but the small-n
warning chip fires. Horizon capping kicks in (likely capped to 6 months
even when 12 is requested). Engine D and Engine C lines diverge because
the cohort cell is dense and informative.

---

## 10-row checklist (run per lifter)

For each of Lifter A / B / C, walk these rows. Pass = ✅, fail = ❌, note
the symptom in one line. Re-test on both desktop (Chrome) and mobile
(360 px viewport via DevTools device emulator).

| # | Check | Lifter A | Lifter B | Lifter C |
|---|---|---|---|---|
| 1 | Engine D toggle is visible on the Athlete Projection panel (gate at `/api/athlete/projection-engines` is open) | | | |
| 2 | Switching Engines C → D changes the projected line visibly (line redraws, summary numbers update) | | | |
| 3 | Prediction interval band is reasonable — not degenerate-narrow (≤2 kg), not meaningless-wide (≥80 kg at 12-month horizon) | | | |
| 4 | Fallback indicator surfaces correctly. Lifter A: no banner. Lifter B: "all lifts fell back" banner. Lifter C: small-n warning chip. | | | |
| 5 | Bracket-transition seam (if `meta.bracket_transitions > 0`) renders without visual artifact — no double-line, no gap | | | |
| 6 | Mobile 360 px layout: chart fits, legend doesn't overflow, dropdowns reachable, toggle still visible | | | |
| 7 | Cold-start wall-clock note (open in fresh incognito after backend has been idle 15 min). Target ≤2s with disk-load path. Record observed seconds. | | | |
| 8 | Browser console clean — zero Recharts `width(-1) height(-1)` warnings on tab switch, zero fetch errors, zero React key warnings | | | |
| 9 | Methodology disclaimer on the Athlete Projection tab references both Engines and explains the toggle's meaning | | | |
| 10 | About page renders the v3 schema artifact (no schema-mismatch fallback message, MAPE table populates) | | | |

---

## Verification commands (for sanity-checking before walking)

Confirm Engine D is live and the three lifters still match the path
signals documented above before starting the walk:

```bash
# Verify Engine D gate is open + convergence rate
curl -s https://cpu-analytics-backend.onrender.com/api/athlete/projection-engines

# Verify Lifter A still clean Engine D
curl -s "https://cpu-analytics-backend.onrender.com/api/athlete/Mark%20Tobias/projection?horizon_months=12&engine=mixed_effects" \
  | python -c "import sys,json;d=json.load(sys.stdin);m=d['meta'];print('div=',d['age_division'],'bracket=',m['lifter_bracket']['bracket'],'n_cell=',m['lifter_bracket']['n_cell'],'partial=',m['engine_d_partial'])"

# Verify Lifter B still whole-cell fallback
curl -s "https://cpu-analytics-backend.onrender.com/api/athlete/Bruce%20Markham/projection?horizon_months=12&engine=mixed_effects" \
  | python -c "import sys,json;d=json.load(sys.stdin);m=d['meta'];print('fallback_lifts=',m['engine_d_fallback_lifts'])"

# Verify Lifter C still small-n + clean
curl -s "https://cpu-analytics-backend.onrender.com/api/athlete/Matthias%20Bernhard/projection?horizon_months=12&engine=mixed_effects" \
  | python -c "import sys,json;d=json.load(sys.stdin);m=d['meta'];print('small_n=',m['small_n_warning'],'horizon_capped=',d['horizon_capped'])"
```

If any of the three lifters no longer match (e.g. new meets shifted the
bracket, or convergence changed after a data refresh), substitute via
`/api/lifters/search?q=<partial>` and re-pick by re-running the verifier.

---

## PI-width baseline (2026-05-20)

Measured during the polish-sweep + Scout-MVP sprint (Stage 2b, plan
`where-did-we-leave-elegant-sifakis.md`). Twelve-month horizon. Sign-off:
**OK — no widths exceed the 100 kg per-lift flag threshold; synthesis
looks reasonable.**

Method: `curl /api/athlete/<name>/projection?horizon_months=12&engine=<C|D>`
on the live backend. Width = `upper_kg - lower_kg` of the last
`projected_points` entry per lift. Quadrature sum =
`2 * sqrt(sum((width/2)^2))` across S/B/D.

| Lifter | Path | Engine | S | B | D | Sum | Quad |
|---|---|---|---|---|---|---|---|
| Mark Tobias | clean Engine D (Open, n=20, bracket 105-110, n_cell=22) | C | 35.7 | 27.6 | 34.4 | 97.7 | 56.7 |
| Mark Tobias | (same) | D | 51.0 | 35.1 | 55.0 | 141.1 | 82.8 |
| Bruce Markham | whole-cell fallback (M2, n=21, bracket 90-95 merged through >=120, n_cell=3) | C | 52.5 | 34.7 | 41.3 | 128.5 | 75.3 |
| Bruce Markham | (same) | D | 52.5 | 34.7 | 41.3 | 128.5 | 75.3 |
| Matthias Bernhard | sparse clean D (Jr, n=3, bracket 70-80, n_cell=156, small_n_warning=True) | C | 49.1 | 31.0 | 48.8 | 128.9 | 75.9 |
| Matthias Bernhard | (same) | D | 38.8 | 21.1 | 42.8 | 102.7 | 61.5 |

### Reading

1. **Mark Tobias (clean D, data-rich).** Engine D *widens* PIs vs Engine C
   by ~40-60% per lift. The MixedLM's per-meet noise (`residual_var`) for
   this cell is materially larger than Engine C's per-lifter residual sigma.
   Plausible — Engine C residuals are computed from one lifter's polyfit;
   `residual_var` aggregates across the whole cohort cell. No flag.
2. **Bruce Markham (whole-cell fallback).** Widths identical to Engine C
   exactly. Confirms the fallback path returns the Engine C result
   numerically untouched. `engine_d_note` reads "All lifts fell back to
   Engine C: no converged MixedLM cell for this lifter's (division,
   bracket)." Correct.
3. **Matthias Bernhard (sparse clean D).** Engine D *narrows* widths vs
   Engine C by ~20-30%. Cohort prior dominates for small-n lifters and
   is tighter than the personal-polyfit residual. Resolves the
   2026-05-01 follow-up concern from the opposite direction: not too
   tight to flag (61.5 kg quadrature sum is reasonable for a 12-mo
   projection), but worth noting that data-sparse lifters get the
   biggest variance pull from the cohort.

### Decision

Synthesis is producing reasonable PIs across the three reference paths.
No follow-up needed unless the Arc 6 walk surfaces a lifter where
widths exceed the 100 kg per-lift flag threshold OR widths are
visually degenerate (< 2 kg).

The 2026-05-01 follow-up question ("blend in `random_intercept_var`")
is **resolved**: the current synthesis is not too tight in aggregate.
Re-open only if a future data refresh shows a per-lift width >100 kg
on a healthy lifter.

---

## After the walk

- If all 30 cells (10 rows × 3 lifters) pass: append a one-line entry to
  `NEXT_STEPS.md` under the "Session plan -- 2026-05-01" section noting
  Arc 6 closed on YYYY-MM-DD.
- Per-row failures: open a P1 entry in `NEXT_STEPS.md` with the failing
  row number, lifter, and observed symptom.
- Console warnings from row 8: even one Recharts `width(-1)` warning
  signals the inactive-tab gating regressed — see `CLAUDE.md` "Recharts +
  display:none" gotcha.
