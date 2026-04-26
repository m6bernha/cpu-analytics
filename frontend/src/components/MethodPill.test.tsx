// Tests for MethodPill — the chart-method badge with click-to-open tooltip.
// Uses raw vitest assertions (the project's tsconfig does not pull in
// jest-dom's type augmentation, matching the convention in useUrlState.test).

import { afterEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { MethodPill } from './MethodPill'

describe('MethodPill', () => {
  afterEach(() => {
    cleanup()
  })

  it('renders the lifter-lookup variant label', () => {
    render(<MethodPill variant="lifter-lookup" />)
    expect(
      screen.queryByText(/Linear regression — this lifter only/i),
    ).not.toBeNull()
  })

  it('renders the athlete-projection variant label', () => {
    render(<MethodPill variant="athlete-projection" />)
    expect(
      screen.queryByText(/Engine C — cohort-aware Bayesian/i),
    ).not.toBeNull()
  })

  it('opens the tooltip when the info button is clicked', () => {
    render(<MethodPill variant="lifter-lookup" />)
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /method details/i }))
    expect(screen.queryByRole('tooltip')).not.toBeNull()
  })

  it('closes the tooltip on Escape', () => {
    render(<MethodPill variant="lifter-lookup" />)
    fireEvent.click(screen.getByRole('button', { name: /method details/i }))
    expect(screen.queryByRole('tooltip')).not.toBeNull()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('closes the tooltip on outside mousedown', () => {
    render(
      <div>
        <MethodPill variant="lifter-lookup" />
        <button data-testid="outside">outside</button>
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: /method details/i }))
    expect(screen.queryByRole('tooltip')).not.toBeNull()
    fireEvent.mouseDown(screen.getByTestId('outside'))
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('flips aria-expanded when toggled', () => {
    render(<MethodPill variant="athlete-projection" />)
    const trigger = screen.getByRole('button', { name: /method details/i })
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(trigger)
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
  })
})
