// Tests for Banner — the small inline notice block used by AthleteProjection
// and other tabs. Mirrors MethodPill.test.tsx style: raw vitest assertions,
// no jest-dom matchers.

import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { Banner } from './Banner'

describe('Banner', () => {
  afterEach(() => {
    cleanup()
  })

  it('renders children content', () => {
    render(<Banner tone="warning">Heads up</Banner>)
    expect(screen.queryByText('Heads up')).not.toBeNull()
  })

  it('applies warning (orange) classes when tone="warning"', () => {
    const { container } = render(<Banner tone="warning">x</Banner>)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toMatch(/border-orange-900/)
    expect(root.className).toMatch(/bg-orange-950/)
    expect(root.className).toMatch(/text-orange-300/)
  })

  it('applies info (zinc) classes when tone="info"', () => {
    const { container } = render(<Banner tone="info">x</Banner>)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toMatch(/border-zinc-800/)
    expect(root.className).toMatch(/bg-zinc-900/)
    expect(root.className).toMatch(/text-zinc-300/)
  })
})
