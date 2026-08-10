// MeetRecapCard -- 3:4 portrait recap of ONE meet performance, built to be
// screenshot- and PNG-export-friendly. Sits beside AthleteCard on the
// profile and renders from the same `LifterHistory` payload, so it costs
// no extra API call.
//
// Why a single meet rather than a calendar year. The obvious framing was
// Spotify-Wrapped, a year in review, and the data killed it: 62.9% of
// lifter-years in the Canada+IPF pool contain exactly ONE meet, so a
// yearly card would tell most lifters "you did 1 meet". A meet recap
// works for 100% of lifters instead of 37%, and the moment someone
// actually wants to post is the evening after competing.
//
// What it deliberately does NOT show, decided at design time: PR flags and
// change-since-last-meet. This card is about the performance itself, not a
// progress narrative, and both of those need a second meet to mean
// anything. AthleteCard already carries the career arc.

import type { Ref } from 'react'

import type { LifterHistory, LifterMeet } from '../lib/api'
import { fmtKg } from '../lib/format'
import { athletePath } from '../lib/route'
import type { PercentileCurves } from '../lib/percentile'
import { PercentileBadge } from './PercentileBadge'

interface MeetRecapCardProps {
  lifter: LifterHistory
  meet: LifterMeet
  /** GLP percentile curves; the badge self-hides when absent. */
  percentileCurves?: PercentileCurves
  ref?: Ref<HTMLDivElement>
}

export function MeetRecapCard({
  lifter,
  meet,
  percentileCurves,
  ref,
}: MeetRecapCardProps) {
  const context = [
    meet.CanonicalWeightClass ? `${meet.CanonicalWeightClass} kg` : null,
    meet.Division,
    meet.Equipment,
  ]
    .filter(Boolean)
    .join(' · ')

  // Same reasoning as AthleteCard: a downloaded PNG should still point
  // home, and the host is only known at runtime.
  const profileUrl =
    `${typeof window !== 'undefined' ? window.location.host : 'cpu-analytics.vercel.app'}` +
    athletePath(lifter.name)

  return (
    <div
      ref={ref}
      data-testid="meet-recap-card"
      className="relative aspect-[3/4] w-full max-w-sm mx-auto rounded-xl ring-2 ring-orange-400/40 bg-zinc-950 p-6"
    >
      <div className="mb-4">
        <p className="text-[11px] uppercase tracking-wider text-orange-300">
          Meet recap
        </p>
        <h2 className="text-xl font-bold text-zinc-100 leading-tight mt-1">
          {lifter.name}
        </h2>
        <p className="text-sm text-zinc-300 mt-1 leading-snug">
          {meet.MeetName ?? 'Unnamed meet'}
        </p>
        <p className="text-xs text-zinc-400 mt-0.5">
          {meet.Date}
          {context && <> · {context}</>}
        </p>
      </div>

      <div className="rounded-lg bg-zinc-900/60 border border-zinc-800 px-4 py-3 mb-4">
        <p className="text-[11px] uppercase tracking-wider text-zinc-400">
          Total
        </p>
        <p className="text-3xl font-bold text-zinc-100 tabular-nums leading-none mt-1">
          {fmtKg(meet.TotalKg, 1)}
          <span className="text-base font-medium text-zinc-400 ml-1">kg</span>
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <Lift label="Squat" kg={meet.Best3SquatKg} />
        <Lift label="Bench" kg={meet.Best3BenchKg} />
        <Lift label="Deadlift" kg={meet.Best3DeadliftKg} />
      </div>

      <div className="rounded-lg bg-zinc-900/60 border border-zinc-800 px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[11px] uppercase tracking-wider text-zinc-400">
            IPF GL Points
          </span>
          <span
            className="text-xl font-bold text-zinc-100 tabular-nums"
            data-testid="meet-recap-glp"
          >
            {meet.Goodlift != null ? meet.Goodlift.toFixed(1) : '—'}
          </span>
        </div>
        <PercentileBadge
          glp={meet.Goodlift}
          sex={lifter.sex}
          curves={percentileCurves}
          className="mt-2"
        />
      </div>

      <div className="absolute bottom-4 left-6 right-6 flex items-end justify-between gap-2">
        <span className="text-[10px] text-zinc-400 truncate">{profileUrl}</span>
        <span className="text-[10px] text-zinc-400 whitespace-nowrap">
          OpenPowerlifting data
        </span>
      </div>
    </div>
  )
}

function Lift({ label, kg }: { label: string; kg: number | null }) {
  return (
    <div className="rounded-lg bg-zinc-900/60 border border-zinc-800 px-2 py-2 text-center">
      <p className="text-[10px] uppercase tracking-wider text-zinc-400">
        {label}
      </p>
      <p className="text-base font-semibold text-zinc-100 tabular-nums mt-0.5">
        {fmtKg(kg, 1)}
      </p>
    </div>
  )
}
