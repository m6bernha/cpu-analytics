import { describe, expect, it } from 'vitest'
import { addDaysISO, fmtDate, fmtDateShort, parseIsoDateParts } from './format'

describe('parseIsoDateParts', () => {
  it('parses a plain date and truncates a full timestamp to its date', () => {
    expect(parseIsoDateParts('2026-03-14')).toEqual([2026, 3, 14])
    expect(parseIsoDateParts('2026-03-14T23:59:00Z')).toEqual([2026, 3, 14])
  })

  it('returns null for empty or malformed input', () => {
    expect(parseIsoDateParts(null)).toBeNull()
    expect(parseIsoDateParts('')).toBeNull()
    expect(parseIsoDateParts('March 14')).toBeNull()
    expect(parseIsoDateParts('2026-03')).toBeNull()
  })
})

describe('addDaysISO', () => {
  it('adds days without drifting across the DST boundary', () => {
    // 2026-03-07 -> +1 crosses North American DST (Mar 8). Local-time
    // setDate math can land on Mar 7 23:00 here; UTC math cannot.
    expect(addDaysISO('2026-03-07', 1)).toBe('2026-03-08')
    expect(addDaysISO('2026-03-07', 2)).toBe('2026-03-09')
  })

  it('rolls over month and year ends', () => {
    expect(addDaysISO('2026-01-31', 1)).toBe('2026-02-01')
    expect(addDaysISO('2026-12-31', 1)).toBe('2027-01-01')
    expect(addDaysISO('2026-03-01', -1)).toBe('2026-02-28')
  })

  it('rounds fractional day offsets and passes bad input through', () => {
    expect(addDaysISO('2026-06-15', 30.4)).toBe('2026-07-15')
    expect(addDaysISO('nonsense', 3)).toBe('nonsense')
  })
})

describe('fmtDate / fmtDateShort', () => {
  it('render the ISO date without a timezone round trip', () => {
    expect(fmtDate('2026-03-14')).toBe('Mar 14, 2026')
    expect(fmtDateShort('2026-03-14')).toBe("Mar '26")
  })

  it('fall back on bad input instead of throwing', () => {
    expect(fmtDate(null)).toBe('—')
    expect(fmtDate('garbage')).toBe('garbage')
    expect(fmtDateShort(undefined)).toBe('')
  })
})
