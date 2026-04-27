// Tests for MethodPill — the clickable cross-tab method picker.
// Uses raw vitest assertions (project's tsconfig does not pull in
// jest-dom's type augmentation, matching useUrlState.test.tsx).

import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { MethodPill } from './MethodPill'

describe('MethodPill', () => {
  afterEach(() => {
    cleanup()
  })

  it('renders the lifter-lookup variant label in the trigger', () => {
    render(<MethodPill variant="lifter-lookup" />)
    expect(
      screen.queryByText(/Linear regression — this lifter only/i),
    ).not.toBeNull()
  })

  it('renders the athlete-projection variant label in the trigger', () => {
    render(<MethodPill variant="athlete-projection" />)
    expect(
      screen.queryByText(/Engine C — cohort-aware Bayesian/i),
    ).not.toBeNull()
  })

  it('opens the method menu on click', () => {
    render(<MethodPill variant="lifter-lookup" />)
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    expect(screen.queryByRole('menu')).not.toBeNull()
  })

  it('lists all three methods inside the menu', () => {
    render(<MethodPill variant="lifter-lookup" />)
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    const menu = screen.getByRole('menu')
    expect(menu.textContent).toMatch(/Linear regression/i)
    expect(menu.textContent).toMatch(/Engine C/i)
    expect(menu.textContent).toMatch(/Engine D/i)
  })

  it('marks Engine D as disabled with a coming-soon note', () => {
    render(<MethodPill variant="athlete-projection" />)
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    const menu = screen.getByRole('menu')
    expect(menu.textContent).toMatch(/Not yet wired/i)
  })

  it('renders the active variant with no nav link, and the other as a link', () => {
    render(<MethodPill variant="lifter-lookup" currentLifter="Test Lifter" />)
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    // Only the engine-c row should render as an anchor (cross-nav). Linear
    // is the active variant; Engine D is disabled.
    const menuitems = screen.getAllByRole('menuitem')
    const anchorCount = menuitems.filter((el) => el.tagName === 'A').length
    expect(anchorCount).toBe(1)
  })

  it('cross-nav anchor preserves the lifter in the destination tab key', () => {
    render(<MethodPill variant="lifter-lookup" currentLifter="Test Lifter" />)
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    const anchor = screen
      .getAllByRole('menuitem')
      .find((el) => el.tagName === 'A') as HTMLAnchorElement | undefined
    expect(anchor).toBeTruthy()
    if (!anchor) return
    const params = new URLSearchParams(anchor.search)
    expect(params.get('tab')).toBe('projection')
    expect(params.get('ap_lifter')).toBe('Test Lifter')
    // Old tab's lifter key is cleared (ap_lifter contains "lifter" as a
    // substring, so URLSearchParams.has is the safe check, not string contains).
    expect(params.has('lifter')).toBe(false)
  })

  it('closes the menu on Escape', () => {
    render(<MethodPill variant="lifter-lookup" />)
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    expect(screen.queryByRole('menu')).not.toBeNull()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('closes the menu on outside mousedown', () => {
    render(
      <div>
        <MethodPill variant="lifter-lookup" />
        <button data-testid="outside">outside</button>
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: /switch projection method/i }))
    expect(screen.queryByRole('menu')).not.toBeNull()
    fireEvent.mouseDown(screen.getByTestId('outside'))
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('flips aria-expanded when toggled', () => {
    render(<MethodPill variant="athlete-projection" />)
    const trigger = screen.getByRole('button', { name: /switch projection method/i })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
  })
})
