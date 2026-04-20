// Smoke tests for key user routes. Requires:
// - Vite dev server (auto-started by Playwright webServer config)
// - Backend running at VITE_API_BASE (default: http://127.0.0.1:8000)
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

// Route 2: QT Squeeze tab
test('/?tab=qt renders QT Squeeze', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=qt')
  await expect(
    page.getByRole('tab', { name: 'QT Squeeze' })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('heading', { name: /QT Squeeze/i })
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

// Route 4: Lifter Lookup with pre-filled lifter — search input pre-filled
test('/?tab=lookup&lifter=Matthias%20Bernhard renders detail', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=lookup&lifter=Matthias%20Bernhard')
  await expect(
    page.getByRole('tab', { name: 'Lifter Lookup' })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('textbox', { name: /search/i })
  ).toHaveValue('Matthias Bernhard')
  check()
})

// Route 5: compare mode with two lifters — compare view renders
test('/?tab=lookup&mode=compare&lifters=... renders compare', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto(
    '/?tab=lookup&mode=compare&lifters=Matthias%20Bernhard,Alex%20Mardell'
  )
  await expect(
    page.getByRole('tab', { name: 'Lifter Lookup' })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('button', { name: /compare/i })
  ).toBeVisible()
  check()
})

// Route 6: manual entry form visible
test('/?tab=lookup&mode=manual shows manual entry form', async ({ page }) => {
  const check = watchConsoleErrors(page)
  await page.goto('/?tab=lookup&mode=manual')
  await expect(
    page.getByRole('tab', { name: 'Lifter Lookup' })
  ).toHaveAttribute('aria-selected', 'true')
  await expect(
    page.getByRole('button', { name: /manual/i })
  ).toBeVisible()
  check()
})
