import { describe, expect, it } from 'vitest'

import {
  formatPercentile,
  percentileFor,
  standingFor,
  type PercentileCurve,
} from './percentile'

// Linear curve: GLP 100..200 across percentiles 0..100, so percentile p
// has GLP 100 + p.
const linear: PercentileCurve = {
  n: 500,
  glp: Array.from({ length: 101 }, (_, i) => 100 + i),
}

describe('percentileFor', () => {
  it('resolves a value to its percentile', () => {
    expect(percentileFor(150, linear)).toBe(50)
    expect(percentileFor(195, linear)).toBe(95)
  })

  it('clamps at the cohort edges', () => {
    expect(percentileFor(50, linear)).toBe(0)
    expect(percentileFor(100, linear)).toBe(0)
    expect(percentileFor(999, linear)).toBe(100)
  })

  it('takes the highest percentile at or below the value', () => {
    // 150.7 sits between the 50th (150) and 51st (151) percentile.
    expect(percentileFor(150.7, linear)).toBe(50)
  })

  it('returns null on missing or non-finite input', () => {
    expect(percentileFor(null, linear)).toBeNull()
    expect(percentileFor(undefined, linear)).toBeNull()
    expect(percentileFor(NaN, linear)).toBeNull()
    expect(percentileFor(150, undefined)).toBeNull()
  })

  it('refuses to rank against a too-small cohort', () => {
    expect(percentileFor(150, { n: 12, glp: linear.glp })).toBeNull()
    expect(percentileFor(150, { n: 500, glp: [] })).toBeNull()
  })
})

describe('formatPercentile', () => {
  it('phrases the upper half as a top-N standing', () => {
    expect(formatPercentile(96)).toBe('Top 4%')
    expect(formatPercentile(100)).toBe('Top 1%')
    expect(formatPercentile(50)).toBe('Top 50%')
  })

  it('phrases the lower half as a plain percentile', () => {
    expect(formatPercentile(30)).toBe('30th percentile')
    expect(formatPercentile(0)).toBe('0th percentile')
  })

  it('passes null through', () => {
    expect(formatPercentile(null)).toBeNull()
  })
})

describe('standingFor', () => {
  const data = {
    window_start: '2024-01-01',
    window_end: '2026-01-01',
    curves: { M: linear },
  }

  it('looks up the curve for the lifter sex', () => {
    expect(standingFor(195, 'M', data)).toEqual({ pct: 95, label: 'Top 5%' })
  })

  it('returns empty standing for an unknown sex or missing data', () => {
    expect(standingFor(195, 'F', data)).toEqual({ pct: null, label: null })
    expect(standingFor(195, null, data)).toEqual({ pct: null, label: null })
    expect(standingFor(195, 'M', undefined)).toEqual({ pct: null, label: null })
  })
})
