// "Top 4%" standing badge, rendered anywhere a GLP score exists.
//
// Phase 0 of the social layer ships the raw percentile rather than a tier
// name; naming is parked (NEXT_STEPS.md). Intensity tracks how high the
// standing is, using the locked palette (coral is the only orange-family
// accent sitewide).

import { standingFor, type PercentileCurves } from '../lib/percentile'

function toneFor(pct: number): string {
  if (pct >= 99) return 'bg-orange-500/15 text-orange-300 border-orange-500/30'
  if (pct >= 95) return 'bg-violet-500/15 text-violet-300 border-violet-500/30'
  if (pct >= 80) return 'bg-blue-500/15 text-blue-300 border-blue-500/30'
  if (pct >= 50) return 'bg-teal-500/15 text-teal-300 border-teal-500/30'
  return 'bg-zinc-800 text-zinc-400 border-zinc-700'
}

export function PercentileBadge({
  glp,
  sex,
  curves,
  className = '',
}: {
  glp: number | null | undefined
  sex: string | null | undefined
  curves: PercentileCurves | undefined
  className?: string
}) {
  const { pct, label } = standingFor(glp, sex, curves)
  if (pct === null || label === null) return null

  const window = curves?.window_start && curves?.window_end
    ? ` (active lifters, ${curves.window_start} to ${curves.window_end})`
    : ''

  return (
    <span
      className={
        'inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border ' +
        toneFor(pct) + (className ? ' ' + className : '')
      }
      title={`IPF GL Points standing among Canadian IPF Raw lifters${window}`}
    >
      {label}
    </span>
  )
}
