// Pure helpers for the meet recap card. Kept out of MeetRecapCard.tsx so
// they are unit-testable without rendering, and so the component file
// only exports a component (react-refresh/only-export-components).

import type { LifterMeet } from './api'

/**
 * A meet is only recappable if it produced a real total.
 *
 * Two exclusions, both of which would otherwise put a false number on a
 * card someone posts publicly:
 *
 *  - A bombed or DQ'd meet is a real row with a null total. There is no
 *    performance to show, and reconstructing one from the partial lifts
 *    would claim a total that was never achieved.
 *  - On a non-SBD entry, `TotalKg` is the partial sum for whichever lifts
 *    were contested, so a bench-only 90 kg would render under a heading
 *    that reads "Total".
 */
export function isRecappable(meet: LifterMeet): boolean {
  return meet.Event === 'SBD' && meet.TotalKg !== null && meet.TotalKg > 0
}

/** Most recent recappable meet, or null when the lifter has none. */
export function latestRecappableMeet(meets: LifterMeet[]): LifterMeet | null {
  const eligible = meets.filter(isRecappable)
  if (!eligible.length) return null
  return eligible.reduce((best, m) => (m.Date > best.Date ? m : best))
}
