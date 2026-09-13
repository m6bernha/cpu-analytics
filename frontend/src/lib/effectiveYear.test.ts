import { describe, expect, it } from 'vitest'
import { FALLBACK_EFFECTIVE_YEAR, resolveEffectiveYear } from './effectiveYear'

describe('resolveEffectiveYear', () => {
  it('uses the fallback while filters have not loaded', () => {
    expect(resolveEffectiveYear(null, undefined)).toBe(FALLBACK_EFFECTIVE_YEAR)
    expect(resolveEffectiveYear(null, [])).toBe(FALLBACK_EFFECTIVE_YEAR)
  })

  it('defaults to the NEWEST year the backend reports, whatever order it arrives in', () => {
    // Negative control against the old hard-coded 2027: a 2028 drop must
    // change the default with no code edit.
    expect(resolveEffectiveYear(null, [2026, 2027, 2028])).toBe(2028)
    expect(resolveEffectiveYear(null, [2028, 2026, 2027])).toBe(2028)
  })

  it('an explicit pick always wins, even an older year', () => {
    expect(resolveEffectiveYear(2026, [2026, 2027, 2028])).toBe(2026)
  })
})
