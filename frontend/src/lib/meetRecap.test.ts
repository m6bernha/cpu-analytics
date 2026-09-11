import { describe, expect, it } from 'vitest'
import type { LifterMeet } from './api'
import { isRecappable, latestRecappableMeet } from './meetRecap'

// Only the fields the helpers read matter; the rest are filler so the
// object satisfies the LifterMeet shape.
function meet(over: Partial<LifterMeet>): LifterMeet {
  return {
    Name: 'Test Lifter', Sex: 'M', Federation: 'CPU', Country: 'Canada',
    Equipment: 'Raw', Tested: 'Yes', Event: 'SBD', Division: 'Open',
    Age: 25, CanonicalWeightClass: '83', Date: '2026-03-14',
    TotalKg: 600, Best3SquatKg: 220, Best3BenchKg: 140, Best3DeadliftKg: 240,
    ...over,
  } as LifterMeet
}

describe('isRecappable', () => {
  it('accepts a full-power meet with a real total', () => {
    expect(isRecappable(meet({}))).toBe(true)
  })

  it('rejects a bombed meet: a null total has no performance to show', () => {
    // The card is exported and posted publicly. Reconstructing a total
    // from partial lifts would claim a number the lifter never hit.
    expect(isRecappable(meet({ TotalKg: null }))).toBe(false)
    expect(isRecappable(meet({ TotalKg: 0 }))).toBe(false)
  })

  it('rejects every non-SBD entry: a partial TotalKg would render under "Total"', () => {
    for (const ev of ['B', 'BD', 'SD', 'SB', 'S', 'D', null]) {
      expect(isRecappable(meet({ Event: ev, TotalKg: 90 }))).toBe(false)
    }
  })
})

describe('latestRecappableMeet', () => {
  it('returns null when nothing qualifies', () => {
    expect(latestRecappableMeet([])).toBeNull()
    expect(latestRecappableMeet([meet({ Event: 'B' }), meet({ TotalKg: null })])).toBeNull()
  })

  it('picks the most recent qualifying meet, skipping a newer bench-only or bombed one', () => {
    const rows = [
      meet({ Date: '2025-01-10', TotalKg: 580 }),
      meet({ Date: '2026-06-01', Event: 'B', TotalKg: 150 }),   // newer, bench only
      meet({ Date: '2026-05-01', TotalKg: null }),               // newer, bombed
      meet({ Date: '2026-02-20', TotalKg: 610 }),
    ]
    expect(latestRecappableMeet(rows)?.Date).toBe('2026-02-20')
  })
})
