// MeetRecapCard tests.
//
// The card states a lifter's performance at a named meet on a named date,
// and it is built to be exported and posted. That raises the cost of being
// wrong above the usual: a card that quietly attributes the wrong meet,
// or invents a total for a day someone bombed out, is a public claim about
// a real person. Most of what follows guards that.

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MeetRecapCard } from './MeetRecapCard'
import { isRecappable, latestRecappableMeet } from '../lib/meetRecap'
import type { LifterHistory, LifterMeet } from '../lib/api'

function makeMeet(over: Partial<LifterMeet> = {}): LifterMeet {
  return {
    Name: 'Jane Doe',
    Sex: 'F',
    Federation: 'CPU',
    Country: 'Canada',
    Equipment: 'Raw',
    Tested: 'Yes',
    Event: 'SBD',
    Division: 'Open',
    Age: 27,
    CanonicalWeightClass: '72',
    Date: '2026-03-14',
    TotalKg: 455,
    Best3SquatKg: 165,
    Best3BenchKg: 90,
    Best3DeadliftKg: 200,
    Goodlift: 91.2,
    MeetName: 'Nationals',
    MeetCountry: 'Canada',
    TotalDiffFromFirst: 55,
    DaysFromFirst: 700,
    is_pr: true,
    class_changed: false,
    ...over,
  }
}

function makeLifter(meets: LifterMeet[]): LifterHistory {
  return {
    found: true,
    name: 'Jane Doe',
    sex: 'F',
    meets,
  } as unknown as LifterHistory
}

describe('isRecappable', () => {
  it('accepts a full-power meet with a total', () => {
    expect(isRecappable(makeMeet())).toBe(true)
  })

  it('rejects a bombed meet', () => {
    // A real row in the history table with no performance to show. The
    // card must not invent one from the partial lifts.
    expect(isRecappable(makeMeet({ TotalKg: null }))).toBe(false)
    expect(isRecappable(makeMeet({ TotalKg: 0 }))).toBe(false)
  })

  it('rejects a bench-only meet', () => {
    // TotalKg on a non-SBD entry is the partial sum, so putting it on a
    // card labelled "Total" would overstate the day.
    expect(isRecappable(makeMeet({ Event: 'B', TotalKg: 90 }))).toBe(false)
    expect(isRecappable(makeMeet({ Event: 'BD', TotalKg: 290 }))).toBe(false)
  })
})

describe('latestRecappableMeet', () => {
  it('picks the most recent meet, not the last in array order', () => {
    const meets = [
      makeMeet({ Date: '2026-03-14', MeetName: 'Nationals' }),
      makeMeet({ Date: '2024-09-14', MeetName: 'Older' }),
      makeMeet({ Date: '2025-06-08', MeetName: 'Middle' }),
    ]
    expect(latestRecappableMeet(meets)?.MeetName).toBe('Nationals')
  })

  it('skips a more recent bombed meet in favour of the last real one', () => {
    const meets = [
      makeMeet({ Date: '2025-06-08', MeetName: 'Good day' }),
      makeMeet({ Date: '2026-03-14', MeetName: 'Bombed', TotalKg: null }),
    ]
    expect(latestRecappableMeet(meets)?.MeetName).toBe('Good day')
  })

  it('returns null when nothing is recappable', () => {
    expect(latestRecappableMeet([])).toBeNull()
    expect(latestRecappableMeet([makeMeet({ TotalKg: null })])).toBeNull()
  })
})

describe('MeetRecapCard', () => {
  const lifter = makeLifter([makeMeet()])

  it('leads with the total and shows all three lifts', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet()} />)
    expect(screen.getByText('455.0')).toBeTruthy()
    expect(screen.getByText('165.0')).toBeTruthy()
    expect(screen.getByText('90.0')).toBeTruthy()
    expect(screen.getByText('200.0')).toBeTruthy()
  })

  it('names the meet and the date it is claiming', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet()} />)
    expect(screen.getByText('Nationals')).toBeTruthy()
    expect(screen.getByText(/2026-03-14/)).toBeTruthy()
    expect(screen.getByText('Jane Doe')).toBeTruthy()
  })

  it('shows IPF GL Points', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet()} />)
    expect(screen.getByTestId('meet-recap-glp').textContent).toContain('91.2')
  })

  it('renders a dash rather than a zero when GLP is missing', () => {
    // Equipped and some historical rows have no Goodlift. Printing 0.0
    // would read as a real, terrible score.
    render(
      <MeetRecapCard lifter={lifter} meet={makeMeet({ Goodlift: null })} />,
    )
    expect(screen.getByTestId('meet-recap-glp').textContent).toContain('—')
  })

  it('renders a dash for a missing individual lift', () => {
    render(
      <MeetRecapCard lifter={lifter} meet={makeMeet({ Best3BenchKg: null })} />,
    )
    const card = screen.getByTestId('meet-recap-card')
    expect(card.textContent).toContain('Bench')
    expect(card.textContent).toContain('—')
  })

  it('carries the weight class, division and equipment as context', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet()} />)
    const card = screen.getByTestId('meet-recap-card')
    expect(card.textContent).toContain('72 kg')
    expect(card.textContent).toContain('Open')
    expect(card.textContent).toContain('Raw')
  })

  it('survives an unnamed meet rather than printing null', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet({ MeetName: null })} />)
    expect(screen.getByText('Unnamed meet')).toBeTruthy()
    expect(screen.getByTestId('meet-recap-card').textContent).not.toContain('null')
  })

  it('does NOT show PR or change-since-last-meet claims', () => {
    // Deliberate scope decision: this card is the performance, not a
    // progress narrative. is_pr and TotalDiffFromFirst are both present
    // on the meet object, so leaving them off has to be asserted.
    render(<MeetRecapCard lifter={lifter} meet={makeMeet({ is_pr: true })} />)
    const text = screen.getByTestId('meet-recap-card').textContent ?? ''
    expect(text).not.toMatch(/\bPR\b/)
    expect(text).not.toMatch(/\+55/)
  })

  it('keeps the profile URL on the card so a reposted PNG points home', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet()} />)
    expect(
      screen.getByTestId('meet-recap-card').textContent,
    ).toContain('/athlete/Jane%20Doe')
  })

  it('holds a 3:4 aspect so the export is a predictable shape', () => {
    render(<MeetRecapCard lifter={lifter} meet={makeMeet()} />)
    expect(screen.getByTestId('meet-recap-card').className).toContain(
      'aspect-[3/4]',
    )
  })
})

describe('two entries at one meet on one day', () => {
  // Real case, found on Erik Willis: a Raw entry and a Single-ply entry at
  // Nationals 2020-03-03. Date and meet name are identical, so keying a
  // list on them produced a duplicate React key and made the second entry
  // unselectable. LifterDetail keys the picker on index for this reason,
  // and puts equipment in the option label so the two are distinguishable.
  const sameDay = [
    makeMeet({
      Date: '2020-03-03', MeetName: 'Nationals',
      Equipment: 'Single-ply', TotalKg: 1067.5,
    }),
    makeMeet({
      Date: '2020-03-03', MeetName: 'Nationals',
      Equipment: 'Raw', TotalKg: 950,
    }),
  ]

  it('treats both as recappable rather than collapsing them', () => {
    expect(sameDay.filter(isRecappable)).toHaveLength(2)
  })

  it('renders whichever entry it is handed, not just the first', () => {
    const lifter = makeLifter(sameDay)
    const { unmount } = render(
      <MeetRecapCard lifter={lifter} meet={sameDay[0]} />,
    )
    expect(screen.getByTestId('meet-recap-card').textContent).toContain('Single-ply')
    unmount()

    render(<MeetRecapCard lifter={lifter} meet={sameDay[1]} />)
    const text = screen.getByTestId('meet-recap-card').textContent ?? ''
    expect(text).toContain('Raw')
    expect(text).toContain('950.0')
  })
})
