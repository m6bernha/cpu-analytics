// Default effective year for the Qualifying Totals panel.
//
// The panel used to hard-code 2027 as its initial state, which was right
// in 2026 and would have stayed 2027 forever once CPU published 2028
// standards. The backend already reports every year it has
// (`/api/qt/live/filters` -> `effective_years`), so the default is
// derived from that list and the literal below is only the pre-load
// fallback.

/** Pre-load fallback only; the real default is the newest available year. */
export const FALLBACK_EFFECTIVE_YEAR = 2027

/**
 * The user's explicit pick wins; otherwise the newest year the backend
 * reports; otherwise the fallback while filters are still loading.
 */
export function resolveEffectiveYear(
  pick: number | null,
  available: number[] | undefined,
): number {
  if (pick !== null) return pick
  if (available && available.length) {
    return available.reduce((a, b) => (b > a ? b : a))
  }
  return FALLBACK_EFFECTIVE_YEAR
}
