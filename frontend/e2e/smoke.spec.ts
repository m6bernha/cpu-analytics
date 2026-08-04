// Smoke tests for key user routes. Requires:
// - Vite dev server (auto-started by Playwright webServer config)
// - Backend running at VITE_API_BASE (default: http://127.0.0.1:8000)
//   serving the SYNTHETIC fixtures (python scripts/make_synthetic_data.py).
//   Routes 4-5 assert on fixture lifters (Alice A, Bob B), so a backend
//   on a real preprocessed parquet will fail them. CI wires this up in
//   the e2e job; locally, back up data/processed/ first if it holds a
//   real parquet.
//
// First run: npx playwright install chromium

import { test, expect, type Page, type ConsoleMessage } from '@playwright/test'

// Attach a console error collector and return a checker function.
// Call check() at the end of the test to fail on any console errors.
function watchConsoleErrors(page: Page): () => void {
  const errors: string[] = []
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error') {
      errors.push(msg.text())
    }
  })
  return () => {
    if (errors.length > 0) {
      throw new Error(`Console errors during load:\n${errors.join('\n')}`)
    }
  }
}

// Route 1: landing — Progression tab visible
test('/ loads Progression tab', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/')
  await expect(page.getByRole('tablist', { name: 'Main tabs' })).toBeVisible()
  await expect(
    page.getByRole('tab', { name: 'Progression' })
  ).toHaveAttribute('aria-selected', 'true')
  check()
})

// Route 2: Qualifying Totals tab (URL key stays 'qt' for old deep links)
test('/?tab=qt renders Qualifying Totals', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=qt')
  await expect(
    page.getByRole('tab', { name: 'Qualifying Totals' })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('heading', { name: /Qualifying Totals/i })
  ).toBeVisible()
  check()
})

// Route 3: Lifter Lookup, search mode default — input visible
test('/?tab=lookup shows search input', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=lookup')
  await expect(
    page.getByRole('tab', { name: 'Lifter Lookup' })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('textbox', { name: /search/i })
  ).toBeVisible()
  check()
})

// Route 4: pre-selected lifter renders the detail view. The `lifter` URL
// key selects the lifter directly; the search input stays empty by design
// (query is ephemeral local state). Asserts the detail heading, which
// requires the synthetic fixture backend.
test('/?tab=lookup&lifter=Alice%20A renders detail', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=lookup&lifter=Alice%20A')
  await expect(
    page.getByRole('tab', { name: 'Lifter Lookup' })
  ).toHaveAttribute('aria-selected', 'true')
  // Two headings carry the name (AthleteCard h2 + detail h3); either proves
  // the detail view rendered.
  await expect(page.getByRole('heading', { name: 'Alice A' }).first()).toBeVisible()
  check()
})

// Route 5: compare mode with two fixture lifters — mode pill selected
// (the pills are role=tab, not button) and both lifters render.
test('/?tab=lookup&mode=compare&lifters=... renders compare', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=lookup&mode=compare&lifters=Alice%20A,Bob%20B')
  await expect(
    page.getByRole('tab', { name: /compare/i })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('Alice A').first()).toBeVisible()
  await expect(page.getByText('Bob B').first()).toBeVisible()
  check()
})

// Route 6: manual entry form visible — mode pill selected and the submit
// button rendered.
test('/?tab=lookup&mode=manual shows manual entry form', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=lookup&mode=manual')
  await expect(
    page.getByRole('tab', { name: /manual/i })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('button', { name: /compute trajectory/i })
  ).toBeVisible()
  check()
})
