// AthleteCard -- 3:4 portrait visual summary for a lifter, designed to be
// screenshot- and PNG-export-friendly. Mounts in LifterDetail above the
// existing chart. Renders fully client-side from a `LifterHistory` (the
// same payload powering the chart and meet table); no extra API calls.
//
// Props:
//   lifter: LifterHistory  -- result of fetchLifterHistory()
//   ref?:   Ref<HTMLDivElement>  -- React-19 ref-as-prop, forwarded to the
//          card root so exportCard.ts can capture the node.
//
// Three callout chips:
//   - PR Total (max TotalKg across SBD meets)
//   - PR GLP   (max Goodlift across SBD meets)
//   - Highest tier reached (resolveHighestTier across all meets)
//
// Tier styling pulls from `lib/colors.ts` TIER_TOKENS. Sparkline is a tiny
// inline SVG (no Recharts) so the component renders cleanly under jsdom
// without ResizeObserver mocks. See ADR 0001.

import type { Ref } from 'react'
import type { LifterHistory } from '../lib/api'
import { TIER_TOKENS, type Tier } from '../lib/colors'
import { resolveHighestTier } from '../lib/meetTier'

interface AthleteCardProps {
  lifter: LifterHistory
  ref?: Ref<HTMLDivElement>
}

export function AthleteCard({ lifter, ref }: AthleteCardProps) {
  const meets = lifter.meets ?? []

  const totals = meets
    .map((m) => m.TotalKg)
    .filter((v): v is number => v !== null && v > 0)
  const prTotal = totals.length > 0 ? Math.max(...totals) : null

  const glps = meets
    .map((m) => m.Goodlift)
    .filter((v): v is number => v !== null && v > 0)
  const prGlp = glps.length > 0 ? Math.max(...glps) : null

  const tierResult = resolveHighestTier(
    meets.map((m) => ({ meetName: m.MeetName, meetCountry: m.MeetCountry })),
  )
  const tier: Tier = tierResult.tier
  const tokens = TIER_TOKENS[tier]
  const highlightTier = tier === 'national' || tier === 'international'

  const dates = meets
    .map((m) => m.Date)
    .filter((d): d is string => Boolean(d))
    .sort()
  const firstYear = dates[0]?.slice(0, 4) ?? ''
  const lastYear = dates[dates.length - 1]?.slice(0, 4) ?? ''
  const yearSpan =
    firstYear && lastYear && firstYear !== lastYear
      ? `${firstYear} - ${lastYear}`
      : firstYear || ''

  const sparkPoints = meets
    .map((m) => m.TotalKg)
    .filter((v): v is number => v !== null && v > 0)

  const subtitle = [
    lifter.sex,
    lifter.latest_weight_class,
    lifter.latest_equipment,
  ]
    .filter(Boolean)
    .join(' / ')

  return (
    <div
      ref={ref}
      data-testid="athlete-card"
      data-tier={tier}
      className={`relative aspect-[3/4] w-full max-w-sm mx-auto rounded-xl ring-2 ${tokens.ring} bg-zinc-950 p-6 transition-opacity duration-500`}
    >
      <div
        className={`absolute top-3 right-3 px-2 py-0.5 rounded text-xs font-medium ${tokens.bg} ${tokens.text}`}
        data-testid="athlete-card-tier-chip"
      >
        {tokens.label}
      </div>

      <div className="mb-4 pr-24">
        <h2 className="text-xl font-bold text-zinc-100 leading-tight">
          {lifter.name}
        </h2>
        {subtitle ? (
          <p className="text-sm text-zinc-400 mt-1">{subtitle}</p>
        ) : null}
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <Callout
          label="PR Total"
          value={prTotal != null ? `${prTotal.toFixed(1)} kg` : '-'}
        />
        <Callout
          label="PR GLP"
          value={prGlp != null ? prGlp.toFixed(1) : '-'}
        />
        <Callout
          label="Highest"
          value={tokens.label}
          highlight={highlightTier}
        />
      </div>

      <Sparkline points={sparkPoints} />

      <div className="absolute bottom-3 left-6 right-6 flex items-baseline justify-between text-xs text-zinc-500">
        <span>{lifter.meet_count ?? meets.length} meets</span>
        <span>{yearSpan}</span>
      </div>
    </div>
  )
}

function Callout({
  label,
  value,
  highlight,
}: {
  label: string
  value: string
  highlight?: boolean
}) {
  const wrap = highlight
    ? 'bg-amber-950/30 ring-1 ring-amber-700/40'
    : 'bg-zinc-900 ring-1 ring-zinc-800'
  const text = highlight ? 'text-amber-300' : 'text-zinc-200'
  return (
    <div className={`rounded-md p-2 text-center ${wrap}`}>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">
        {label}
      </div>
      <div className={`text-sm font-semibold mt-0.5 ${text}`}>{value}</div>
    </div>
  )
}

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) {
    return (
      <div
        className="h-20 mt-2 flex items-center justify-center text-xs text-zinc-500"
        data-testid="athlete-card-sparkline-empty"
      >
        Not enough meets to plot
      </div>
    )
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  const W = 280
  const H = 80
  const dx = W / (points.length - 1)
  const path = points
    .map((v, i) => {
      const x = i * dx
      const y = H - ((v - min) / range) * H
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-20 mt-2"
      preserveAspectRatio="none"
      aria-hidden="true"
      data-testid="athlete-card-sparkline"
    >
      <path d={path} fill="none" stroke="#569cd6" strokeWidth="1.5" />
    </svg>
  )
}
