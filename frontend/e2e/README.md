# E2E smoke tests

Playwright smoke tests covering the six key URL routes in cpu-analytics.

## Prerequisites

- Node 18+ with `npm install` already run in `frontend/`
- Backend running at `VITE_API_BASE` (default: `http://127.0.0.1:8000`). Tests are not mocked — they hit the real API.

## First-time setup

Install the Chromium browser binary (one-time, not committed to git):

```
npx playwright install chromium
```

## Run

```bash
# From frontend/
npm run test:e2e          # headless, HTML report written to playwright-report/
npm run test:e2e:ui       # interactive UI mode
```

Or directly:

```bash
npx playwright test
npx playwright test --ui
```

## What is tested

| Test | Route |
|------|-------|
| Progression tab loads | `/` |
| QT Squeeze renders | `/?tab=qt` |
| Lifter Lookup search input visible | `/?tab=lookup` |
| Pre-filled lifter detail | `/?tab=lookup&lifter=Matthias%20Bernhard` |
| Compare mode renders | `/?tab=lookup&mode=compare&lifters=Matthias%20Bernhard,Alex%20Mardell` |
| Manual entry form visible | `/?tab=lookup&mode=manual` |

Each test also fails if any `console.error` fires during page load.

## CI

Not wired into CI yet. Strategic follow-up decision deferred.
