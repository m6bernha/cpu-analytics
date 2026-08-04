# ADR 0002: Stateless social layer (Arena-inspired)

- Status: accepted
- Date: 2026-08-04
- Input: [Arena Powerlifting teardown](../research/arena-teardown-2026-08.md)
  plus a decision interview with Matthias the same day.

## Context

Matthias wants the Arena Powerlifting experience on cpu-analytics: athlete
discovery, rankings, sharing. The teardown found Arena's replicable core is
a social-discovery layer over the same OpenPowerlifting data this site
already ships, and its only hard moat (live meet scoreboards via meet
partnerships) is explicitly out of scope for a solo dev.

## Decisions (locked in the 2026-08-04 interview)

1. **No accounts, no database.** Everything ships stateless over the
   existing parquet + DuckDB stack. Claiming, follows, and email
   notifications are deferred until the stateless layer proves demand.
   The auth platform decision (Supabase was the leading candidate) is
   deliberately NOT made now.
2. **Stateless-first build order.** Phase 0 tiers + leaderboard, Phase 1
   public profiles + share cards + meet pages. Accounts are Phase 3+,
   gated on a future decision.
3. **Real URLs with per-athlete OG cards.** `/athlete/{name}` paths plus
   a Vercel Edge Function rendering per-athlete og:image cards, so shared
   links preview with the lifter's name, total, and tier.
4. **Canada + IPF scope only**, consistent with `backend/app/scope.py`.
   "Best in Canada by GLP" is the story; global rankings are Arena's
   territory. `openipf_global.parquet` stays a preprocess flag, not a
   product surface.

## Design

### Tier system (Phase 0)

Five tiers from IPF GL percentile within the Canada+IPF cohort, per sex,
computed over each lifter's best GLP score (SBD Raw):

| Tier | Percentile |
|---|---|
| Legend | top 1% |
| Elite | top 5% |
| Gold | top 20% |
| Silver | top 50% |
| Bronze | rest |

Thresholds computed in DuckDB at request time (the cohort is ~5,400
lifters; a percentile query is milliseconds) behind a small
`/api/tiers` endpoint returning the per-sex GLP cutoffs plus the
distribution histogram. Tier assignment is then client-side arithmetic
anywhere a GLP score exists (athlete cards, leaderboard rows, Scout).
Exact percentile edges and naming can be tuned at implementation.

### Leaderboard (Phase 0)

New "Rankings" tab. Backend `GET /api/leaderboard` with filters (sex,
weight class, division, equipment, metric = GLP | total) and
limit/offset pagination, SQL-aggregated in DuckDB (same pattern as
`qt._load_best_totals_per_era`, never pull the scope into pandas).
Columns: rank, name (links to profile), class, best total, GLP, tier
badge, last meet date. `staleTime` 10 min like other static-ish queries.

### Public athlete profiles (Phase 1)

`/athlete/{encoded-name}` real path. v1 slug is the URL-encoded exact
name (OpenIPF names are the primary key; hyphenated pretty slugs would
collide with hyphenated names, revisit later). SPA routing stays
hand-rolled in the existing useUrlState philosophy: App.tsx reads
`location.pathname`, a `vercel.json` SPA fallback rewrites all paths to
index.html. The page composes existing pieces: AthleteCard (+ tier
badge), LifterDetail history chart + meet table, share button, link to
Athlete Projection with the lifter preloaded.

### Per-athlete OG cards (Phase 1)

Vercel Edge Function `/api/og/athlete?name=` renders a 1200x630 card
(name, tier, best total, GLP) via @vercel/og. Edge Middleware injects
`og:image` + `og:title` into the HTML response for `/athlete/*`
requests so crawlers see per-athlete metadata without SSR-ing the app.
The card pulls numbers from the public backend API. This is the one new
infrastructure piece; it stays on Vercel Hobby free tier.

### Meet result pages (Phase 1)

`/meet/{encoded-meetname}/{date}` backed by `GET /api/meet` grouping
parquet rows by class and placing. Static results only, no live
anything. Every athlete name links to their profile; every profile's
meet table links to meet pages. This closes the internal link graph for
SEO.

### Share cards (Phase 1)

Extend the existing AthleteCard PNG export (html-to-image, already
shipped) with the tier badge and the profile URL. Native share sheet on
touch (ShareButton already does this).

## Out of scope, revisit only on demand signal

- Accounts, claiming, follows, email notifications (Phase 3+, needs the
  auth-platform decision first).
- Live meet scoreboards, team/coach dashboards (Arena's moat, requires
  partnerships).
- Global leaderboards.

## Sequencing and estimates

| Phase | Work | Estimate |
|---|---|---|
| 0 | /api/tiers + tier badges + Rankings tab | 1-2 sessions |
| 1a | Path routing + /athlete/{name} profile page | 1 session |
| 1b | OG edge function + middleware | 1 session |
| 1c | Meet pages + cross-linking | 1 session |
| 1d | Share-card tier polish + mobile pass | 0.5 session |

Phase 0 has no routing risk and ships value alone; start there.
