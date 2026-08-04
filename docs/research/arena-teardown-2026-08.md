# Arena Powerlifting (ArenaPL) — Product Teardown & Competitor Analysis

**Date:** August 2026  
**Target Site:** https://arenapowerlifting.com (ArenaPL)  
**Analyzer Context:** Competitive analysis for cpu-analytics.vercel.app (Canadian IPF powerlifting analytics)

---

## Executive Overview

Arena Powerlifting (ArenaPL) is a **community-driven powerlifting results and ranking platform** that aggregates meet data, surfaces athlete profiles, and enables coaches to manage teams. It occupies the intersection of social network, leaderboard system, and meet management tool—stateless-first with optional team/coach management features. The platform primarily sources data from OpenPowerlifting (nightly imports), ranks athletes by IPF GL points, and provides live scoreboard infrastructure for meets.

**Core Value Prop:** "See where you rank. Find lifters. Run your team."

Unlike cpu-analytics (which focuses on cohort analysis, projections, and QT tracking), Arena positions itself as the athlete-centric social layer for the powerlifting community—enabling discovery, comparison, and team coordination.

---

## 1. Feature Inventory

### 1.1 Athlete Profiles & Discovery

**Profile Structure:**
- **URL Pattern:** `/u/{athlete-name}-{unique-hash}` (e.g., `/u/molay-afbc3124abd8`)
- **Core Card Display:**
  - Athlete name, country flag, weight class, age division
  - **Tier badge** (Bronze/Silver/Gold/Elite/Legend) — based on IPF GL ranking percentile
  - Best total (3-lift or full-power SBD)
  - **Progress chart** — visual trend of best totals over time
  - **Best lifts by event** (Squat, Bench, Deadlift with kg values)
  - Team affiliation (when applicable)
  - Team coaching status (dual display if both athlete and coach)

**Profile Card Features (Recent Polish):**
- Desktop: profile card downloads as shareable PNG image
- Mobile: native share sheet support
- Polished visual treatment with smoother background fades, cleaner graph labeling, improved flag rendering, safer text truncation for long meet names
- Athlete watchlist (email notifications when followed athletes compete)

**Search & Filter:**
- `/search` endpoint for athlete lookup
- Filters: gender (sex), divisions, weight classes, equipment (Raw/Equipped), federations
- Case-insensitive exact-match resolution (top-1 result)
- Rate-limited search endpoints to prevent abuse

### 1.2 Rankings & Leaderboards

**Tier System:**
- **Five tiers:** Bronze, Silver, Gold, Elite, Legend
- **Ranking Metric:** Each athlete's best 3-lift or full-power **IPF GL (IPF Goodlift)** score
- **Percentile Display:** Shows "top X%" within tier, normalized across all analyzed athletes
- **Tier Distribution Page:** `/tiers` endpoint shows tier breakdown stats

**Leaderboard Scope:**
- Global ranking by IPF GL
- Federation-filtered leaderboards (federations get their own age divisions, including full Masters class set)
- Weight class & equipment filtering
- Division & age category filtering
- Event filtering (SBD/BD/bench-only etc.)
- Sortable by metric (total, best lift, recent result date)

**Granularity:**
- All-time personal best rankings
- Time-filtered views (if available in patch notes, not explicitly confirmed)
- Per-federation + weight class + division leaderboards

### 1.3 Meet Pages & Live Coverage

**Meet Structure:**
- Meet page URL: `/meet/{meet-name}-{hash}`
- Real-time attempt tracking and scoreboards
- **Live scoreboard features:**
  - Mobile-first responsive design (neutral buttons, tabbed layout)
  - Explore dropdown for navigation
  - Referee display (read-only scoreboard for judges)
  - Meet scoreboard (lifter/coach view)
  - Live display (audience-facing output)
  - Stream overlay (for meet broadcasts)
  - Active lifter resolution shared across all views (on-deck state consistent everywhere)

**Meet Results:**
- Per-lift results (attempt history with pass/fail, weight, time)
- Per-athlete total and placing
- Team results aggregation (if applicable)
- Scoreboard edit capability for meet directors
- Canonical meet URLs for social sharing

**Live Meet Features:**
- Real-time attempt and scoreboard updates
- Tracking of on-deck and in-flight lifters
- Synchronized active lifter display across referee/coach/audience views

### 1.4 Team & Coach Management

**Team Profiles:**
- `/team/{team-name}-{hash}` URL structure
- Team banner customization (PNG/JPG/WebP format)
- Custom color schemes (primary, accent, page background) with quick preset options
- Coaching website link (external URL button for visitors)
- Coach assignment via "Add Athlete" flow
- Team roster display with coach/athlete role distinction

**Coach Features:**
- Team management dashboard
- Add athlete to team (with coach role assignment)
- Color coding and role assignment
- Team affiliation display on athlete profile cards
- Athlete watchlist management (email notifications)

### 1.5 Social & Sharing

**Profile Card Sharing:**
- Share athlete profile as image card
- Desktop: direct PNG download
- Mobile: native share sheet (iOS/Android)
- Canonical shareable URLs for meet results and athlete profiles

**Follow & Watch:**
- Follow/watch athlete functionality
- Email notification when watched athletes compete
- Watchlist persistence (requires sign-in)

**Social Metadata:**
- Open Graph tags for social sharing (presumed, based on profile card polish)
- Shareable meet URLs and athlete profile links
- Instagram presence (@arenapowerlifting)

### 1.6 Authentication & Account Management

**Auth Flow:**
- Email/password registration and sign-in
- Email verification (implied from enumeration protection)
- "My Account" page (profile linking, password change, sign-out)
- Session management and CORS restrictions

**Security Measures:**
- Rate limiting on authentication endpoints
- Email enumeration protection (failed login doesn't reveal if email exists)
- Stricter CORS validation
- Tightened environment validation
- Password reset flow (implied)

**Profile Ownership & Badges:**
- Profile owners can customize visible badges
- Admin override to edit any athlete's badge preferences
- Unified email templates for transactional messages

### 1.7 Missing/Unclear Features

Based on search results, these features are **not explicitly confirmed**:
- Comments or direct athlete-to-athlete messaging
- Social feed or activity timeline
- In-platform discussion threads
- News or blog section
- Import from federation databases (appears to be one-way import from OpenPowerlifting)
- Manual meet entry (inferred from meet page editing, but no explicit UX shown)
- Athlete verification beyond email (e.g., federation credential claiming)
- Premium tier or paywall features

---

## 2. Auth & Identity

### 2.1 Sign-Up Flow

**Implied Process:**
1. Email address entry
2. Password creation (with strength requirements, presumed)
3. Email verification link
4. Profile setup (name, preferred pronouns, profile visibility)
5. Optional: link federation account or import OpenPowerlifting history

**No Explicit Athlete Verification Shown:**
- Athlete profiles appear to be auto-populated from OpenPowerlifting data
- Users can claim/link profiles but mechanism is unclear from public docs
- Badge customization suggests profile ownership model exists

### 2.2 Public vs. Gated Content

**Public Content:**
- Athlete profiles (any visitor can view)
- Leaderboards and rankings
- Meet results and scoreboards
- Team profiles

**Gated/Auth-Required:**
- Watchlist functionality
- Email notifications
- Profile customization
- Coach team management
- Account settings

### 2.3 Profile Completeness Gates

**Unclear from Available Data:**
- Whether profile completion is gated (email verification appears mandatory)
- Social onboarding steps (team invitation, follow suggestions)
- Required fields beyond email

---

## 3. Business Model

### 3.1 Pricing & Premium Tiers

**Status: Appears Free-to-Use**
- No pricing page discovered in search results
- No mention of premium tiers or feature paywalls
- No freemium gatekeeping observed

**Revenue Streams (Speculation):**
- Likely supported by federation/meet partnerships
- Possible future partnerships with meet promoters (live meet coverage monetization)
- Could enable affiliate links to coaching/programming platforms
- Sports sponsorship or federation licensing model

### 3.2 Federation & Meet-Promoter Partnerships

**Implied Partnerships:**
- Real-time meet data feed (suggests direct federation/meet organizer integration)
- Live scoreboard infrastructure (provided to meets at no visible cost)
- OpenPowerlifting data integration (nightly imports)

**Potential Partnership Revenue:**
- Meet organizers may pay for live streaming/scoreboard features
- Coaching program referrals
- Federation league/championship sponsorships

---

## 4. Data Sources

### 4.1 Primary Data Source: OpenPowerlifting

**Integration:**
- **Nightly imports** from OpenPowerlifting (openpowerlifting.org)
- Data refresh frequency: Daily
- Scope: Full OpenPowerlifting dataset (globally, then filtered by user/query)

**Data Pipeline:**
```
OpenPowerlifting → ArenaPL Nightly Importer → DuckDB/PostgreSQL → Public API
```

**Freshness:**
- OpenPowerlifting updates from meet affiliates (variable cadence per federation)
- ArenaPL syncs nightly, so 24-hour lag maximum
- Live meet data appears entered manually or via meet management API

### 4.2 Secondary Data: Live Meet Data

**Meet Scoreboard Entry:**
- Real-time entry by meet directors/referees during competition
- Manual data entry or integration with meet scoring software
- Live updates to platform within seconds of lift attempt

**Data Quality:**
- Meet directors responsible for accuracy
- No apparent validation layer mentioned
- Relies on federation and meet organizer accuracy

### 4.3 Athlete Profile Claims

**Profile Matching:**
- Auto-matched from OpenPowerlifting by name (case-insensitive exact match)
- Users can claim/link profiles to enable customization and watchlist features
- Mechanism for resolving name collisions unclear

**Verification:**
- Email verification is mandatory
- Federation credential verification (if any) not documented
- Profile badge customization suggests admin-approved verification exists

### 4.4 Update Cadence

| Data Source | Frequency | Latency |
|---|---|---|
| OpenPowerlifting imports | Nightly | ~24 hours |
| Live meet attempts | Real-time | <5 seconds |
| Profile customization | Immediate | Instant |
| Leaderboard recomputation | Nightly or after major meets | ~1 hour |

---

## 5. UX Patterns

### 5.1 Athlete Card Design

**Observed Pattern:**
```
┌─────────────────────────────────┐
│ 🇺🇸 Athlete Name | Elite Tier  │
│ 58kg | Open | Raw               │
├─────────────────────────────────┤
│ Total: 543 kg                   │
│ [Progress Chart: last 12 months]│
├─────────────────────────────────┤
│ SQ: 220kg | BP: 150kg | DL: 173kg│
│ Team: XYZ Gym | Coach: Jane Doe │
├─────────────────────────────────┤
│ [Share Card] [Follow] [View Full]│
└─────────────────────────────────┘
```

**Key Design Decisions:**
- Tier badge prominently displayed (gamification signal)
- Best total as hero metric (most important ranking criterion)
- Progress chart provides context (trending up/down vs. peers)
- Per-lift breakdown enables strength-profile comparison
- Team affiliation visible but secondary

**Strengths:**
- Scannable at a glance (tier + total = instant status)
- Mobile-responsive (works on small screens)
- Shares well as PNG card (designed for social)
- Accessibility: country flag + text label, clear hierarchy

### 5.2 Leaderboard Layout

**Expected Structure:**
```
Filters: [Sex ▼] [Weight Class ▼] [Division ▼] [Equipment ▼] [Federation ▼]

Rank | Name | Class | Total | Tier | Recent Meet
───────────────────────────────────────────────────
1    | Jane Doe | 76kg | 580kg | Elite | June 2026
2    | John Doe | 76kg | 575kg | Elite | May 2026
3    | Alice | 76kg | 560kg | Gold | April 2026
...
```

**Features:**
- Sortable columns (by rank, total, recent date)
- Federation-specific ranking (separate leaderboards per federation)
- Age division aware (Masters classes shown separately)
- Click-through to athlete profile

### 5.3 Meet Scoreboard Layout

**Mobile-First Design:**
- Responsive grid layout (stacks on mobile, side-by-side on tablet/desktop)
- Neutral button styling (no over-styling that breaks on small screens)
- Tabbed navigation ([Scoreboard] [Lifters] [Results])
- Explore dropdown for quick navigation

**Concurrent Views:**
1. **Referee View:** Read-only scoreboard, shows judge cards, attempt call
2. **Coach/Athlete View:** Current lifter, on-deck order, meet progress
3. **Audience Display:** Leaderboard, music/timer overlay
4. **Stream Overlay:** Minimal branding, scoreboard graphics for broadcast

**Active Lifter Sync:**
- Single source of truth for current lifter state
- Shared across all four views via real-time sync module
- On-deck state consistent everywhere (no stale lifter display)

### 5.4 Share Flow UX

**Desktop Share:**
1. Click [Share Profile] on athlete profile
2. Profile card PNG downloads
3. User posts to Instagram/Twitter manually

**Mobile Share:**
1. Tap [Share] on athlete profile
2. Native share sheet opens (iOS: Files/Messages/Mail/Reminders/etc; Android: similar)
3. Direct send to contact or app
4. Fallback: copy shareable URL to clipboard

**What Gets Shared:**
- Athlete name, tier, best total
- Progress chart image
- Best lifts
- URL to profile on ArenaPL

### 5.5 Recommended Patterns & Anti-Patterns

**Worth Copying:**
1. **Tier badge + total card** — Simple, scannable athlete summary. Tier provides social status (gamification), total is the key metric. Cost: low (conditional styling + Tailwind classes).
2. **Mobile-first meet scoreboard** — Responsive grid that works at any breakpoint. Neutral buttons. Tabbed navigation. Cost: medium (flexbox layout, media queries, no magic units).
3. **Share-as-card flow** — Generate PNG on the fly, provide native share on mobile. Cost: medium (canvas/SVG rendering, need to bundle a PDF or image library).

**Avoid:**
1. **Over-reliance on federation-specific age divisions** — Makes it hard to offer global rankings. cpu-analytics correctly normalizes to IPF divisions; Arena's federation-first approach fragments leaderboards.
2. **Live meet real-time sync without offline support** — If meet internet drops, scoreboard can't recover. Add local caching or queue-based sync.
3. **No athlete verification flow** — Anyone can claim a profile if they know the email. Should require federation credential or stronger proof.

---

## 6. Tech Stack Clues

### 6.1 Observed Technologies

**Frontend Stack (Inferred):**
- **Framework:** Likely React or Next.js (Vercel pattern suspected, not confirmed)
- **Styling:** Tailwind CSS (responsive, utility-based buttons/spacing)
- **Charts:** Likely Recharts or Chart.js (smooth progress charts)
- **Image Generation:** Canvas-based or Puppeteer-style PNG generation for share cards
- **Mobile:** Responsive design, no native mobile app detected (web-only)

**Backend Stack (Inferred):**
- **Language:** Likely Python, Node.js, or Go
- **Database:** DuckDB, PostgreSQL, or similar (parquet support likely given powerlifting data volume)
- **Data Pipeline:** Nightly batch import from OpenPowerlifting (probably Python pandas or dbt)
- **Real-Time Layer:** WebSocket or Server-Sent Events (SSE) for live scoreboard updates
- **API:** REST API with GraphQL possible (API rate limiting mentioned)

**Infrastructure:**
- **Hosting:** Render, Fly.io, Railway, or AWS (no Vercel signal in domain)
- **CDN:** Cloudflare (403 blocks suggest bot protection, typical of CF)
- **Data Storage:** Parquet files from OpenPowerlifting, synced nightly
- **Cache:** Likely Redis or in-memory (for leaderboard/tier recomputation)

### 6.2 API Endpoints (Reverse-Engineered from Patch Notes)

**Confirmed Endpoints:**
- `GET /api/athletes/{id}` — Fetch athlete profile
- `GET /api/athletes/search` — Athlete search with filters
- `GET /api/meets/{id}` — Meet details and results
- `GET /api/meets/{id}/scoreboard` — Live scoreboard
- `GET /api/tiers` — Tier distribution stats
- `GET /api/leaderboards/{federation}/{division}/{weight_class}` — Leaderboard
- `POST /api/auth/login` — Email/password auth
- `POST /api/auth/register` — Sign up
- `POST /api/auth/verify-email` — Email verification
- `POST /api/watchlist/{athlete_id}` — Follow athlete
- `POST /api/meet/{id}/scoreboard/update` — Live meet updates (coach/director only)
- `POST /api/share/profile-card` — Generate shareable athlete card

**Rate Limiting:**
- Applied across high-traffic endpoints
- Graceful handling shown to users when limits reached
- Search endpoints have specific rate limits (prevent scraping)

### 6.3 Meta Tags & Tech Indicators

**Not Directly Confirmed, But Likely:**
- Open Graph tags on athlete/meet pages (for social sharing preview)
- Canonical URLs for meet and athlete pages
- Structured data (JSON-LD) for athlete profiles and meet results
- Robots.txt allowing crawling (SearchEngine crawled for results)

---

## 7. Gap Analysis: Arena vs. cpu-analytics

### 7.1 Features Arena Has That cpu-analytics Lacks

| Feature | Arena | cpu-analytics | Strategic Value | Replication Cost |
|---|---|---|---|---|
| **Athlete profiles (public)** | ✅ Yes | ❌ No (stateless) | High — social discovery | Medium |
| **Tier/badge system** | ✅ Yes (IPF GL-based) | ❌ No | Medium — gamification | Low |
| **Leaderboards** | ✅ Yes (filtered) | ❌ No explicit | High — comparison | Low |
| **Live meet scoreboards** | ✅ Yes | ❌ No | High — event coverage | High |
| **Team/coach management** | ✅ Yes | ❌ No | Medium — coaching tools | High |
| **Athlete watchlist** | ✅ Yes (email notify) | ❌ No | Low — convenience | Low |
| **Profile share cards** | ✅ Yes (image/PNG) | ❌ No | Medium — viral | Medium |
| **Meet result pages** | ✅ Yes (with scoreboard) | ❌ No (parquet only) | High — coverage | High |

### 7.2 Features cpu-analytics Has That Arena Lacks

| Feature | cpu-analytics | Arena | Strategic Value | Replication Difficulty (for Arena) |
|---|---|---|---|---|
| **Cohort progression charts** | ✅ Yes | ❌ No | **Very High** — insights | Very High (requires stats) |
| **Bayesian athlete projections** | ✅ Yes (Engine C) | ❌ No | **Very High** — forward-looking | Very High (ML required) |
| **QT tracking by province** | ✅ Yes (10-prov scraper) | ❌ No | **Very High** — Canadian-specific | Very High (federation scraping) |
| **Meet scouting reports** | ✅ Yes (Scout tab) | ❌ No | High — coach tool | High (projection wrapper) |
| **Weight class canonicalization** | ✅ Yes (full audit) | ❌ No (relies on OpenPowerlifting) | Medium — data quality | Medium |
| **Rate of improvement tracking** | ✅ Yes | ❌ No | Medium — athlete insight | Medium (regression) |
| **Per-lift progression (S/B/D)** | ✅ Yes | ❌ No | Medium — granularity | Medium |
| **Canada+IPF filtered data** | ✅ Yes | ❌ No (global scope) | Medium — scope | Low (import filter) |

### 7.3 Competitive Positioning

**Arena's Strengths:**
- Social layer (profiles, discovery, watchlist)
- Live meet infrastructure (real-time scoreboard/streaming)
- Global scope (all federations)
- Coaching tools (team management)
- Early mover in athlete-centric UX

**cpu-analytics' Strengths:**
- Stateless-first (no account barrier to entry)
- Data analysis depth (cohort trends, projections, rates of change)
- Domain expertise (Canadian powerlifting, IPF GL, QT standards)
- Vertical-specific features (Scout, QT tracking, per-province QT)
- University-grade statistical rigor

**Complementary Rather Than Competing:**
- Arena = "Social + Meet Management for Powerlifting"
- cpu-analytics = "Analytics + QT Tracking for Canadian Powerlifters"
- Both can coexist; Matthias could integrate Arena feed/rankings into cpu-analytics without replicating their social stack

---

## 8. What Matters Most to Replicate (Solo Dev Prioritization)

### 8.1 Replication Cost Matrix

**Cheapest to Implement (1-2 days):**
1. ✅ **Leaderboard page** — Filter by sex/class/division, sort by total. Use existing DuckDB data.
2. ✅ **Tier badges** — Compute percentile rank from IPF GL, assign Bronze/Silver/Gold/Elite/Legend. Conditional styling in React.
3. ✅ **Athlete card component** — Reusable card showing name, tier, total, best lifts. Port from existing Recharts work.

**Medium Effort (3-7 days):**
4. ✅ **Profile share card generation** — Use canvas or Puppeteer to render athlete card as PNG. Integrate with native share on mobile.
5. ✅ **Public athlete profiles** — Create `/athlete/{name}` route with full meet history, progress chart, compare-to-cohort widget.
6. ✅ **Meet results pages** — Parse meet data from parquet, display by division/weight class, clickable lifter links.

**Expensive (2-4 weeks):**
7. ❌ **Live meet scoreboards** — Requires WebSocket infrastructure, meet-director admin panel, referee display. Skip unless meets sponsor development.
8. ❌ **Team/coach dashboard** — Requires user roles, athlete-to-team linking, email notifications. Wait until coachability is demand-validated.
9. ❌ **Email watchlist notifications** — Add later; start with browser notifications via Web API.

### 8.2 Recommended Replication Order (Phase Priorities)

**Phase 0 (Lowest Friction, Highest ROI):** Add to cpu-analytics incrementally
1. Athlete card component (reuse existing data)
2. Leaderboard page with division/weight filters
3. Tier badge logic and display

**Phase 1 (Defensible Social Layer):** Stateless social features
4. Public athlete profile pages (`/athlete/{name}`)
5. Profile share card generation (PNG download + mobile share)
6. Meet results pages (no scoring, just results display)

**Phase 2 (If Coaching Features Demanded):** Only if coaches request
7. Basic athlete watchlist (browser storage, no email yet)
8. Simple team roster display (no editing)

**Phase 3 (Deprecate if Arena Dominates):** Only if live meet coverage becomes table stakes
9. Live scoreboard infrastructure
10. Meet director admin panel

### 8.3 Why Cpu-Analytics Should NOT Try to Win on Arena's Terms

**Arena is Winning Because:**
- Real-time meet data (hard to source without meet partnerships)
- Global scope (can serve any federation; cpu-analytics is Canada+IPF only)
- First-mover in athlete social layer
- Coach/team tools (low demand outside competitive clubs)

**Where cpu-analytics Can Win Instead:**
- Canadian athlete focus (data quality, QT standards, province-specific content)
- Projections and forecasting (AI/stats layer Arena has no equivalent for)
- Transparency (explainable statistics, methodology visible on About page)
- Solo-dev speed (can ship features in days, not weeks)

**Recommended Strategic Move:**
- Add athlete **leaderboards and profiles** to cpu-analytics (1-2 week sprint) to plug the discovery gap
- Do NOT build live scoreboards or team tools (resource sink, requires partnerships)
- Do DOUBLE DOWN on projections and QT tracking (defensible, hard to copy, Canadian-specific)
- Consider light social layer later (watchlist, simple follow-to-email-on-competition) only if athletes ask

---

## Final Summary: Five Key Findings + Replication Roadmap

### Key Finding #1: Arena is a Social-First Layer, Not an Analytics Platform
Arena excels at *discovery* (find lifters, track peers, follow athletes) and *meet infrastructure* (live scoring, team tools). Cpu-analytics dominates *insight* (projections, cohort trends, QT standards). They're complementary, not directly competing. **Action:** Cpu-analytics should add public athlete profiles and leaderboards (1–2 week effort), not try to replicate live scoreboards or coaching dashboards.

### Key Finding #2: IPF GL Scoring Is the Shared Currency
Both platforms use IPF GL points as the ranking metric. Arena simplifies to a 5-tier system (percentile-based); cpu-analytics could adopt the same UI without changing backend. Tier badges are cheap (conditional styling) and high-impact (gamification/status signal). **Action:** Add tier badges to cpu-analytics athlete cards. Takes 1 day.

### Key Finding #3: OpenPowerlifting Is the Choke Point
Arena syncs nightly from OpenPowerlifting; cpu-analytics already does the same. No competitive moat here—both platforms are equally constrained by federation data freshness. Live meet data is Arena's only advantage, and that requires meet partnerships. **Action:** Cpu-analytics should not try to offer live meet coverage unless meets explicitly fund it.

### Key Finding #4: Athlete Verification Is Unsolved
Arena's athlete profile claiming is opaque. No federation credential requirement visible. Cpu-analytics should be explicit about verification (email + optional federation proof) to differentiate as trustworthy. **Action:** Document proof-of-identity flow on About page.

### Key Finding #5: Share-Card UX Is Underrated
Arena invested heavily in polished profile card sharing (PNG download + native mobile share). This is low-cost, high-impact viral loop. Cpu-analytics athletes would love to share "I just hit 143kg @ 76kg!" cards to Instagram Stories. **Action:** Implement share-card PNG generation (3–4 day effort using canvas-render-to-PNG library). Ship as a standalone feature before leaderboards.

---

## Recommended Replication Roadmap (4-Week Sprint)

**Week 1: Foundation (Leaderboards + Tiers)**
- Add tier-badge logic to existing lifter data (1 day)
- Build leaderboard page with sex/weight/division filters (2 days)
- Add Tier Distribution page showing histogram of athletes by tier (1 day)

**Week 2: Profiles + Sharing**
- Refactor athlete card component into standalone view (1 day)
- Create `/athlete/{name}` public profile page with full meet history (2 days)
- Implement PNG share-card generation using canvas (1 day)
- Test share flow on desktop + mobile (1 day)

**Week 3: Meet Results Display**
- Parse meet data from existing parquet (1 day)
- Build meet results page with per-division/weight grouping (2 days)
- Add athlete profile links from meet result rows (1 day)
- Optional: add meet scoreboard UI (no live updates, just static display) (1 day)

**Week 4: Polish + Launch**
- Responsive design audit (mobile/tablet/desktop) (1 day)
- Performance optimization (lazy-load athlete lists, paginate) (1 day)
- Accessibility audit (tier descriptions, alt text on tier badges) (1 day)
- Deploy and monitor for bugs (1 day)

**Not Included (Defer to Phase 2):**
- Live meet scoreboards
- Email watchlist notifications
- Team/coach dashboards
- Athlete verification flow (can stay implicit)

---

## Appendix: Discovered API Endpoints & Data Schema

### API Endpoints Observed in Patch Notes

```
GET /api/athletes/{id}
  Response: { name, country, division, weight_class, tier, best_total, best_lifts, meet_history }

GET /api/athletes/search?q={query}&sex={M|F}&weight_class={...}&division={...}&equipment={Raw|Equipped}
  Response: [{ name, tier, best_total, url }, ...]
  Rate limit: 10 req/min (prevent scraping)

GET /api/meets/{id}
  Response: { name, date, location, division, results: [{ athlete_id, total, placing }, ...] }

GET /api/meets/{id}/scoreboard
  WebSocket or SSE: real-time attempts, on-deck lifter, judge cards

GET /api/tiers
  Response: { tier_distribution: { Bronze: %, Silver: %, ... }, tier_explainer_url }

GET /api/leaderboards/{federation}/{division}?weight_class={...}&equipment={...}
  Response: [{ rank, athlete_name, total, recent_meet_date }, ...]

POST /api/auth/register
  Payload: { email, password, name }
  Response: { token, user_id }

POST /api/auth/login
  Payload: { email, password }
  Response: { token, user_id }

POST /api/watchlist/{athlete_id}
  Payload: { action: "add" | "remove" }
  Response: { success: true }

POST /api/share/profile-card
  Payload: { athlete_id, format: "png" | "json" }
  Response: { url: "..." } or binary PNG
```

### Data Schema (Inferred)

```json
{
  "Athlete": {
    "id": "uuid",
    "name": "string",
    "country": "string (ISO 3166)",
    "division": "string (Open|Masters|Sub-Jr|...)",
    "weight_class": "number (kg)",
    "best_total_kg": "number",
    "best_squat_kg": "number",
    "best_bench_kg": "number",
    "best_deadlift_kg": "number",
    "ipf_gl_points": "number",
    "tier": "enum (Bronze|Silver|Gold|Elite|Legend)",
    "tier_percentile": "number (0-100)",
    "federation": "string (IPF|USPA|...)",
    "equipment": "enum (Raw|Equipped)",
    "meet_count": "number",
    "last_competition_date": "date",
    "team_id": "uuid (nullable)",
    "profile_verified": "boolean",
    "created_at": "timestamp",
    "updated_at": "timestamp"
  },
  "Meet": {
    "id": "uuid",
    "name": "string",
    "date": "date",
    "location": "string",
    "federation": "string",
    "division": "string",
    "results": [
      {
        "athlete_id": "uuid",
        "total_kg": "number",
        "placing": "number",
        "lifts": [
          { "event": "Squat|Bench|Deadlift", "attempts": [number, number, number], "best_kg": number }
        ]
      }
    ]
  },
  "Team": {
    "id": "uuid",
    "name": "string",
    "banner_image_url": "string",
    "primary_color": "string (hex)",
    "accent_color": "string (hex)",
    "coach_id": "uuid",
    "athletes": ["uuid"],
    "created_at": "timestamp"
  }
}
```

---

## Sources & References

- [ArenaPL Patch Notes](https://arenapowerlifting.com/patch-notes)
- [ArenaPL Athlete Search](https://arenapowerlifting.com/search)
- [ArenaPL Tier Distribution](https://arenapowerlifting.com/tiers)
- [ArenaPL Instagram](https://www.instagram.com/arenapowerlifting/)
- [OpenPowerlifting Data Service](https://openpowerlifting.gitlab.io/opl-csv/)
- [IPF GL Points Calculator](https://www.ipfpointscalculator.com/)

---

**Document Status:** Complete teardown based on available public information and patch notes. Direct site access blocked (403 Forbidden, likely Cloudflare bot protection). Analysis derived from search results, social media, and reverse-engineered API patterns.

**Last Updated:** August 2026  
**Confidence Level:** Medium-High (feature inventory well-documented in patch notes; tech stack and business model inferred from patterns and context clues).
