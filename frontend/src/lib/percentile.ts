// Client-side percentile resolution against the per-sex GLP curves from
// GET /api/rankings/percentiles.
//
// The backend ships one GLP value per whole percentile (101 ascending
// floats per sex) so any lifter's standing resolves locally, with no
// per-lifter round trip. Tier NAMES are deliberately not shipped yet:
// Matthias chose raw percentile display for v1 and parked naming
// (see NEXT_STEPS.md).

export interface PercentileCurve {
  n: number
  glp: number[]
}

export interface PercentileCurves {
  window_start: string | null
  window_end: string | null
  curves: Record<string, PercentileCurve>
}

// Below this many lifters a percentile is noise, not a standing.
export const MIN_COHORT_FOR_PERCENTILE = 30

/**
 * Percentile rank (0-100) of `glp` within the cohort curve, or null when
 * the inputs cannot support one. 100 means at or above the top of the
 * cohort.
 */
export function percentileFor(
  glp: number | null | undefined,
  curve: PercentileCurve | undefined,
): number | null {
  if (glp == null || !Number.isFinite(glp)) return null
  if (!curve || curve.glp.length === 0) return null
  if (curve.n < MIN_COHORT_FOR_PERCENTILE) return null

  const arr = curve.glp
  if (glp <= arr[0]) return 0
  if (glp >= arr[arr.length - 1]) return 100

  // Binary search for the highest index whose value is <= glp. Index is
  // the percentile because the curve is sampled at whole percentiles.
  let lo = 0
  let hi = arr.length - 1
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2)
    if (arr[mid] <= glp) lo = mid
    else hi = mid - 1
  }
  return lo
}

/**
 * Display string for a percentile, phrased as standing rather than rank:
 * "Top 4%" for the upper half, "Top 50%" at the median, and plain
 * percentile wording below it (where "top N%" would read as a put-down
 * and is also less informative).
 */
export function formatPercentile(pct: number | null): string | null {
  if (pct == null) return null
  const top = 100 - pct
  if (top <= 0) return 'Top 1%'
  if (pct >= 50) return `Top ${Math.max(1, Math.round(top))}%`
  return `${Math.round(pct)}th percentile`
}

/** Convenience: curve lookup + percentile + label in one call. */
export function standingFor(
  glp: number | null | undefined,
  sex: string | null | undefined,
  data: PercentileCurves | undefined,
): { pct: number | null; label: string | null } {
  if (!data || !sex) return { pct: null, label: null }
  const pct = percentileFor(glp, data.curves[sex])
  return { pct, label: formatPercentile(pct) }
}
