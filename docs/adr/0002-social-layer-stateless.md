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
| 0 | ~~/api/tiers + tier badges + Rankings tab~~ **SHIPPED 2026-08-04** | 1 session |
| 1a | ~~Path routing + /athlete/{name} profile page~~ **SHIPPED 2026-08-04** | 1 session |
| 1b | ~~OG edge function + middleware~~ **SHIPPED 2026-08-04** | 1 session |
| 1c | ~~Meet pages + cross-linking~~ **SHIPPED 2026-08-05** | 1 session |
| 1d | ~~Share-card polish + mobile pass~~ **SHIPPED 2026-08-05** | 0.5 session |

Phase 0 has no routing risk and ships value alone; start there.

## Phase 0 as built (2026-08-04)

Three deviations from the design above, all deliberate:

1. **No tier names.** Matthias chose to ship the raw percentile ("Top 4%")
   and defer naming until the distribution has been live. The five-tier
   percentile table survives only as badge color thresholds. See the
   backlog entry in NEXT_STEPS.md.
2. **No equipment filter.** The design listed one, but IPF GL coefficients
   are defined for Raw Classic SBD only, so an equipped row scored on the
   same curve would be meaningless. Rankings are Raw SBD only.
3. **Endpoints named `/api/rankings` and `/api/rankings/percentiles`**
   rather than `/api/tiers`, matching what they actually return.

Also added: the leaderboard is scoped to lifters **active in the last 24
months**, a question the design did not settle. The window anchors to the
newest meet in the parquet rather than wall-clock today.

## Phase 1a as built (2026-08-04)

Built to spec (hand-rolled routing, URL-encoded exact-name slug, app shell
retained, composes the existing LifterDetail). Two decisions the design did
not settle:

1. **Legacy `?tab=lookup&lifter=X` links redirect** to `/athlete/X` rather
   than both URLs coexisting, so there is one canonical URL per athlete.
   Compare links (`mode=compare`) and the bare lookup tab are untouched —
   they are workspaces, not profiles. Unrelated params (era, view_mode)
   ride along.
2. **The redirect runs in `main.tsx` before the first render**, not in an
   effect. An effect is too late: `useRoute` registers its listener in a
   passive effect, which runs *after* layout effects, so a redirect fired
   from a layout effect dispatches to nobody and the app renders the shell
   instead of the profile. This was caught in the browser, not by tests.

The tab stack stays mounted-but-hidden while a profile is open so tab state
survives the round trip; `isActive` is forced false for every tab in that
state so no Recharts container renders at 0x0.

## Phase 1b as built (2026-08-04)

Built to spec (`@vercel/og` edge function + edge middleware injecting
`og:*` into the SPA shell). Decisions the design did not settle:

1. **Cold-backend fallback.** The backend is Render free tier (up to ~50 s
   cold start) but crawlers give up in ~5-10 s. Both the card endpoint and
   the middleware call the backend with a 3 s `AbortSignal.timeout` and
   degrade rather than fail: the card falls back to a name-only branded
   layout, the description falls back to a generic line. A plainer preview
   beats a broken one.
2. **24 h cache on cards**, overriding `@vercel/og`'s 1-year immutable
   default, which would freeze a lifter's numbers in every shared link
   forever. Weekly data refresh means a day is comfortably fresh.
   Middleware HTML gets `s-maxage=3600`.
3. **Middleware applies to humans too**, not just crawlers. No user-agent
   sniffing to get wrong, and `curl` reproduces exactly what a crawler
   sees.
4. **Meta tags are replaced, not appended.** `index.html` already ships
   site-wide `og:*`/`twitter:*`; appending would leave two competing
   `og:title` values. `injectAthleteMeta` strips the tags it owns and
   re-emits each once. It is a pure string transform in `src/lib/ogMeta.ts`
   so it is unit-testable without an edge runtime (11 cases, including
   attribute-escape).

**The first deploy of this phase FAILED, and the fix is instructive.**

`api/` and `middleware.ts` sit outside `tsconfig.app.json`'s
`include: ["src"]`, so no local gate checked them. A hand-check was run
first, but it passed explicit `--jsx --moduleResolution bundler --types
node` flags. Vercel uses none of those: it reads the ROOT `tsconfig.json`,
which was solution-style (`files: []` + references, no `compilerOptions`),
so it fell back to `moduleResolution: node16` with no JSX support and no
node types. Deploy `dpl_MbYmZcar...` failed on TS17004 (no `--jsx`),
TS2835 (extensionless relative imports) and TS2591 (no `process` type)
while build, tests, and the hand-check were all green.

The lesson is not "check by hand" — it is that a hand-check with
self-chosen flags does not model the compiler that actually runs. Fixed
three ways:

1. `tsconfig.json` gained a `compilerOptions` block. It is ignored by
   `tsc -b` (the referenced projects carry their own) and exists purely so
   Vercel compiles the edge layer with the right options.
2. New `tsconfig.edge.json` covering `api/**/*` + `middleware.ts`, wired
   into `npm run build`, so CI now fails on these files. Verified by
   negative control: removing `jsx` from it reproduces Vercel's exact
   TS17004.
3. Relative imports carry explicit `.js` extensions, valid under both
   node16 and bundler resolution, so the code no longer depends on which
   one is in effect.

Blast radius held as designed: the failed deploy left the previous
deployment serving, so the live site was never broken.

## Phase 1c as built (2026-08-05)

`/meet/{encoded-name}/{date}` + `GET /api/meet`, cross-linked with
profiles in both directions. Decisions and one data finding:

1. **Complete record, not Raw SBD.** Unlike Rankings, a meet page lists
   every event and equipment category, so a bench-only or equipped lifter
   does not vanish from their own meet. Groups are sex -> equipment ->
   event -> weight class.
2. **Meet OG cards** reuse the Phase 1b edge layer: a second card function
   (`api/og/meet.tsx`) and a second middleware matcher, with
   `injectMeetMeta` delegating to the same replace-don't-append transform.
3. **No meets index.** Discovery is Rankings -> profile -> meet -> other
   profiles, which closes the crawl loop per the design.

**Data finding that shaped the page.** The design said "group by class and
placing", but CPU awards placings PER DIVISION, so one weight class
legitimately holds several 1st places. Worse, at Nationals 2026-03-14 two
lifters share Open 83 kg 1st with *no column in the source data
distinguishing them* — verified by checking the raw OpenIPF CSV, where
`MeetTown`/`MeetState` (dropped by preprocess) are identical
(`St. John's, NL`) for all 866 rows. So this is ambiguous upstream, not a
preprocessing loss, and adding those columns would not fix it.

The page therefore presents results as a RECORD: ordered by division then
place, division always visible, and a methodology note saying placings are
reproduced as recorded. It never picks or implies a single winner.

Also surfaced honestly: the parquet is Country=Canada scoped, so an
international meet shows the Canadian contingent only. Responses carry
`canadian_scope_only` and the UI states it when `meet_country != Canada`.

## Phase 1d as built (2026-08-05) — Phase 1 COMPLETE

Smaller than specced, because the percentile badge already landed on
AthleteCard in Phase 0. What remained:

1. **The card now carries its own profile URL.** A downloaded PNG
   reposted to Instagram previously had no attribution and no way back.
   The footer renders `{host}/athlete/{encoded-name}` under the meet
   count, `break-all` so a long encoded name stays inside the 3:4 frame.
   Host comes from `window.location` at runtime, so dev cards say
   localhost and production cards say the real domain.
2. **Responsive columns on the two new tables**, using the
   `hidden sm:table-cell` / `hidden md:table-cell` convention LifterDetail
   already used. Phones keep the columns that matter: meet pages show
   Pl / Lifter / Total, Rankings shows # / Lifter / Standing / Total.

Verified at real widths rather than by inspection: at 375 px the meet
table fits its 343 px container with no horizontal scroll and no body
overflow, and at 1280 px all nine columns return — the columns are
responsive, not deleted.

One measurement gotcha worth recording: with the browser pane not
compositing, `window.innerWidth` reads 0 and every `offsetParent`
visibility check reports hidden, which looks exactly like a broken
layout. Set an explicit viewport size and use `getComputedStyle().display`
instead of trusting `offsetParent` in that state.
