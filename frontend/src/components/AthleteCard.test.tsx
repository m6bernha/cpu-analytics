// AthleteCard tests. Mirrors Banner.test.tsx style: raw vitest, RTL render,
// no jest-dom matchers. Uses inline LifterHistory fixtures rather than
// MSW -- the card has no network calls of its own.

import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { createRef } from 'react'
import { AthleteCard } from './AthleteCard'
import type { LifterHistory, LifterMeet } from '../lib/api'

afterEach(() => {
  cleanup()
})

function makeMeet(overrides: Partial<LifterMeet> = {}): LifterMeet {
  return {
    Name: 'Test Lifter',
    Sex: 'M',
    Federation: 'CPU',
    Country: 'Canada',
    Equipment: 'Raw',
    Tested: 'Yes',
    Event: 'SBD',
    Division: 'Open',
    Age: 25,
    CanonicalWeightClass: '83',
    Date: '2024-06-01',
    TotalKg: 600,
    Best3SquatKg: 200,
    Best3BenchKg: 150,
    Best3DeadliftKg: 250,
    Goodlift: 80,
    MeetName: 'Local Open',
    MeetCountry: 'Canada',
    TotalDiffFromFirst: 0,
    DaysFromFirst: 0,
    is_pr: false,
    class_changed: false,
    ...overrides,
  }
}

function makeLifter(meets: LifterMeet[], extras: Partial<LifterHistory> = {}): LifterHistory {
  return {
    name: 'Test Lifter',
    found: true,
    sex: 'M',
    latest_equipment: 'Raw',
    latest_weight_class: '83',
    meet_count: meets.length,
    best_total_kg: Math.max(0, ...meets.map((m) => m.TotalKg ?? 0)),
    rate_kg_per_month: null,
    weight_class_changes: [],
    projection: null,
    percentile_rank: null,
    meets,
    ...extras,
  }
}

describe('AthleteCard', () => {
  it('renders the lifter name', () => {
    const lifter = makeLifter([makeMeet()])
    render(<AthleteCard lifter={lifter} />)
    expect(screen.queryByText('Test Lifter')).not.toBeNull()
  })

  it('renders the subtitle (sex / weight class / equipment)', () => {
    const lifter = makeLifter([makeMeet()])
    render(<AthleteCard lifter={lifter} />)
    expect(screen.queryByText('M / 83 / Raw')).not.toBeNull()
  })

  it('shows the max TotalKg in the PR Total chip', () => {
    const meets = [
      makeMeet({ TotalKg: 550 }),
      makeMeet({ TotalKg: 650, Date: '2024-08-01' }),
      makeMeet({ TotalKg: 600, Date: '2024-12-01' }),
    ]
    render(<AthleteCard lifter={makeLifter(meets)} />)
    expect(screen.queryByText('650.0 kg')).not.toBeNull()
  })

  it('shows the max Goodlift in the PR GLP chip', () => {
    const meets = [
      makeMeet({ Goodlift: 75 }),
      makeMeet({ Goodlift: 88.5, Date: '2024-08-01' }),
      makeMeet({ Goodlift: 80, Date: '2024-12-01' }),
    ]
    render(<AthleteCard lifter={makeLifter(meets)} />)
    expect(screen.queryByText('88.5')).not.toBeNull()
  })

  it('uses local tier (zinc ring) when all meets are local', () => {
    const lifter = makeLifter([makeMeet({ MeetName: 'London Open' })])
    const { container } = render(<AthleteCard lifter={lifter} />)
    const root = container.querySelector('[data-testid="athlete-card"]') as HTMLElement
    expect(root.dataset.tier).toBe('local')
    expect(root.className).toMatch(/ring-zinc-500/)
  })

  it('uses national tier (amber ring) when a Nationals meet is present', () => {
    const lifter = makeLifter([
      makeMeet({ MeetName: 'BCPA Fall Classic' }),
      makeMeet({ MeetName: 'Nationals', Date: '2025-03-01' }),
    ])
    const { container } = render(<AthleteCard lifter={lifter} />)
    const root = container.querySelector('[data-testid="athlete-card"]') as HTMLElement
    expect(root.dataset.tier).toBe('national')
    expect(root.className).toMatch(/ring-amber-400/)
  })

  it('elevates to international when any meet is non-Canada', () => {
    const lifter = makeLifter([
      makeMeet({ MeetName: 'Nationals' }),
      makeMeet({ MeetName: 'IPF Worlds', MeetCountry: 'Sweden' }),
    ])
    const { container } = render(<AthleteCard lifter={lifter} />)
    const root = container.querySelector('[data-testid="athlete-card"]') as HTMLElement
    expect(root.dataset.tier).toBe('international')
    expect(root.className).toMatch(/ring-amber-300/)
  })

  it('renders the tier chip with the correct label', () => {
    const lifter = makeLifter([makeMeet({ MeetName: 'Alberta Provincials' })])
    render(<AthleteCard lifter={lifter} />)
    const chip = screen.queryByTestId('athlete-card-tier-chip')
    expect(chip).not.toBeNull()
    expect(chip?.textContent).toBe('Provincial')
  })

  it('shows dashes for PRs when no meets are present', () => {
    const lifter = makeLifter([])
    render(<AthleteCard lifter={lifter} />)
    const dashes = screen.queryAllByText('-')
    expect(dashes.length).toBeGreaterThanOrEqual(2)
  })

  it('shows the empty-sparkline placeholder when fewer than 2 meets', () => {
    const lifter = makeLifter([makeMeet({ TotalKg: 600 })])
    render(<AthleteCard lifter={lifter} />)
    expect(screen.queryByTestId('athlete-card-sparkline-empty')).not.toBeNull()
    expect(screen.queryByTestId('athlete-card-sparkline')).toBeNull()
  })

  it('renders the SVG sparkline when 2+ meets exist', () => {
    const meets = [
      makeMeet({ TotalKg: 500, Date: '2023-01-01' }),
      makeMeet({ TotalKg: 600, Date: '2024-06-01' }),
    ]
    render(<AthleteCard lifter={makeLifter(meets)} />)
    expect(screen.queryByTestId('athlete-card-sparkline')).not.toBeNull()
    expect(screen.queryByTestId('athlete-card-sparkline-empty')).toBeNull()
  })

  it('forwards ref to the card root', () => {
    const ref = createRef<HTMLDivElement>()
    render(<AthleteCard lifter={makeLifter([makeMeet()])} ref={ref} />)
    expect(ref.current).not.toBeNull()
    expect(ref.current?.dataset.testid).toBe('athlete-card')
  })
})
