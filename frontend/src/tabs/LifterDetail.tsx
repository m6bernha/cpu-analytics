// Lifter detail subcomponent.
//
// Renders the chart (total or per-lift) + meet table for a single lifter.
// Lazy-loaded from LifterLookup.tsx so Recharts (~200 KB) only ships to
// clients who actually open a lifter detail view or use manual entry.
//
// Do NOT add static imports from this file back into LifterLookup.tsx —
// that would re-merge the lazy chunk into the main bundle and Vite would
// warn INEFFECTIVE_DYNAMIC_IMPORT. Matches the existing CompareView split
// convention.

import { useMemo, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { createPortal } from 'react-dom'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { LifterHistory, LifterMeet, QtStandardRow } from '../lib/api'
import { MethodPill } from '../components/MethodPill'

// ---------- Class-change badge with hover tooltip ----------
//
// Rendered next to the weight class when a lifter's class differs from their
// previous meet. Tooltip renders through a React portal so it escapes the
// table cell's stacking context; this was originally needed because the meet
// wrapper had `overflow-x-auto` (which per CSS spec also clips overflow-y),
// and we keep the portal even now that the wrapper has been reverted to
// `mt-6` without scroll so the pattern stays robust against a future
// wrapper that reintroduces clipping.

function ClassChangeBadge({ label }: { label: string }) {
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  return (
    <>
      <span
        className="ml-1 inline-block text-orange-400 text-xs cursor-help"
        aria-label={label}
        onMouseEnter={(e: ReactMouseEvent<HTMLSpanElement>) => {
          const r = e.currentTarget.getBoundingClientRect()
          setPos({ left: r.left + r.width / 2, top: r.top })
        }}
        onMouseLeave={() => setPos(null)}
      >
        &#9650;
      </span>
      {pos &&
        createPortal(
          <div
            role="tooltip"
            style={{ left: pos.left, top: pos.top - 8 }}
            className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-100 shadow-lg"
          >
            {label}
          </div>,
          document.body,
        )}
    </>
  )
}

// ---------- Date / value formatters ----------

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  // iso is 'yyyy-mm-dd'. Don't pass through Date(iso) — that would interpret
  // it as UTC midnight and can round back to the previous day depending on
  // the viewer's timezone.
  const parts = iso.slice(0, 10).split('-').map(Number)
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso
  const [y, m, d] = parts
  return `${MONTHS[m - 1]} ${d}, ${y}`
}

function fmtKg(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}

function fmtSbd(s: number | null, b: number | null, d: number | null): string {
  if (s == null && b == null && d == null) return '—'
  return `${fmtKg(s)} / ${fmtKg(b)} / ${fmtKg(d)}`
}

function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return ''
  const parts = iso.slice(0, 10).split('-').map(Number)
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso
  const [y, m] = parts
  return `${MONTHS[m - 1]} '${String(y).slice(-2)}`
}

// ---------- QT lookup helper ----------

function findQtForLifter(
  standards: QtStandardRow[] | undefined,
  sex: string | undefined,
  weightClass: string | null | undefined,
): { regionals?: QtStandardRow; nationals?: QtStandardRow } {
  if (!standards || !sex || !weightClass) return {}
  const matches = standards.filter(
    (s) => s.Sex === sex && s.WeightClass === weightClass,
  )
  return {
    regionals: matches.find((m) => m.Level === 'Regionals'),
    nationals: matches.find((m) => m.Level === 'Nationals'),
  }
}

// ---------- Event / era metadata ----------

// Event codes from OpenIPF (see backend KEEP_COLUMNS / data-readme).
// Only SBD (full power) gives a comparable Total. The other event types still
// produce a TotalKg, but it's the partial sum (e.g. just bench for B), so
// plotting them together with SBD on the same y-axis is misleading.
const EVENT_DESCRIPTION: Record<string, string> = {
  SBD: 'Full power',
  BD: 'Push-pull',
  SD: 'Squat + DL',
  SB: 'Squat + bench',
  S: 'Squat only',
  B: 'Bench only',
  D: 'Deadlift only',
}

function eventLabel(ev: string | null | undefined): string {
  if (!ev) return '—'
  return ev
}

function eventTitle(ev: string | null | undefined): string {
  if (!ev) return ''
  return EVENT_DESCRIPTION[ev] ?? ev
}

type Era = 'pre2025' | '2025' | '2027'

const ERA_QT_FIELD: Record<Era, 'QT_pre2025' | 'QT_2025' | 'QT_2027'> = {
  pre2025: 'QT_pre2025',
  '2025': 'QT_2025',
  '2027': 'QT_2027',
}

const ERA_LABEL: Record<Era, string> = {
  pre2025: 'Pre-2025',
  '2025': '2025',
  '2027': '2027',
}

export default function LifterDetail({
  history,
  standards,
  isActive,
  era: eraProp,
  setEra: setEraProp,
  viewMode: viewModeProp,
  setViewMode: setViewModeProp,
}: {
  history: LifterHistory
  standards: QtStandardRow[] | undefined
  isActive: boolean
  // Era + viewMode are URL-backed in LifterLookup so detail views are
  // shareable via a single link. When LifterDetail is used outside the
  // LifterLookup URL-state tree (e.g. manual-entry hypothetical preview),
  // these are optional and fall back to internal state.
  era?: Era
  setEra?: (e: Era) => void
  viewMode?: 'total' | 'per_lift'
  setViewMode?: (v: 'total' | 'per_lift') => void
}) {
  const [eraLocal, setEraLocal] = useState<Era>('2025')
  const [viewModeLocal, setViewModeLocal] = useState<'total' | 'per_lift'>('total')
  const era = eraProp ?? eraLocal
  const setEra = setEraProp ?? setEraLocal
  const viewMode = viewModeProp ?? viewModeLocal
  const setViewMode = setViewModeProp ?? setViewModeLocal

  const qts = findQtForLifter(standards, history.sex, history.latest_weight_class)
  const qtField = ERA_QT_FIELD[era]
  const regionalsQt = qts.regionals?.[qtField]
  const nationalsQt = qts.nationals?.[qtField]

  // Only SBD meets are plotted: the y-axis is "Total (kg)", and on partial
  // events (B, BD, etc.) TotalKg is the partial sum, not a full-power total.
  // Plotting them together would be misleading. Non-SBD meets still appear
  // in the meet table below the chart.
  const sbdMeets = useMemo(
    () => history.meets.filter((m) => m.Event === 'SBD'),
    [history.meets],
  )

  const chartData = useMemo(() => {
    const actual = sbdMeets.map((m: LifterMeet) => ({
      date: m.Date,
      days: m.DaysFromFirst,
      total: m.TotalKg,
      projected: null as number | null,
      upper: null as number | null,
      lower: null as number | null,
      meet: m.MeetName ?? '',
      division: m.Division ?? '',
      weight_class: m.CanonicalWeightClass ?? '',
    }))

    // Append projection points if available. Compute dates using UTC math
    // to avoid DST drift (matching fmtDate's parse-from-ISO convention).
    const proj = history.projection
    if (proj && proj.points.length > 0 && sbdMeets.length > 0) {
      const firstDateStr = sbdMeets[0].Date
      const [fy, fm, fd] = firstDateStr.slice(0, 10).split('-').map(Number)
      const firstUtcMs = Date.UTC(fy, fm - 1, fd)
      for (const pp of proj.points) {
        const futureUtcMs = firstUtcMs + pp.days_from_first * 86_400_000
        const d = new Date(futureUtcMs)
        const iso = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`
        actual.push({
          date: iso,
          days: pp.days_from_first,
          total: null as unknown as number,
          projected: pp.projected_total,
          upper: pp.upper,
          lower: pp.lower,
          meet: '',
          division: '',
          weight_class: '',
        })
      }
      // Bridge: add the last actual point as the first projection point
      // so the dashed line connects to the solid line
      const lastActual = sbdMeets[sbdMeets.length - 1]
      const bridgeIdx = actual.length - proj.points.length
      actual.splice(bridgeIdx, 0, {
        date: lastActual.Date,
        days: lastActual.DaysFromFirst,
        total: lastActual.TotalKg,
        projected: lastActual.TotalKg,
        upper: lastActual.TotalKg,
        lower: lastActual.TotalKg,
        meet: '',
        division: '',
        weight_class: '',
      })
    }

    return actual
  }, [sbdMeets, history.projection])

  const nonSbdCount = history.meets.length - sbdMeets.length

  // Per-lift chart data: includes SBD meets for all three lifts, plus
  // partial-event meets contributing to whichever lift(s) they tested.
  // A bench-only meet contributes to the bench line only.
  const perLiftChartData = useMemo(() => {
    return history.meets
      .filter((m) => m.TotalKg != null)
      .map((m) => ({
        date: m.Date,
        squat: m.Best3SquatKg,
        bench: m.Best3BenchKg,
        deadlift: m.Best3DeadliftKg,
        event: m.Event,
        meet: m.MeetName ?? '',
      }))
  }, [history.meets])

  // Y axis padding so reference lines don't sit on the edge.
  const allTotals = chartData
    .flatMap((d) => [d.total, d.projected, d.upper, d.lower])
    .filter((v): v is number => v != null)
  if (regionalsQt) allTotals.push(regionalsQt)
  if (nationalsQt) allTotals.push(nationalsQt)
  const hasChartData = allTotals.length > 0
  const yMin = hasChartData
    ? Math.floor((Math.min(...allTotals) - 25) / 25) * 25
    : 0
  const yMax = hasChartData
    ? Math.ceil((Math.max(...allTotals) + 25) / 25) * 25
    : 100

  return (
    <div>
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <h3 className="text-zinc-100 text-lg font-semibold">{history.name}</h3>
          <div className="text-zinc-500 text-xs mt-0.5">
            {history.sex} · {history.latest_weight_class} kg · {history.latest_equipment} ·{' '}
            {history.federation}
            {history.country ? ' · ' + history.country : ''}
          </div>
        </div>
        <div className="text-right">
          <div className="text-zinc-200 tabular-nums text-lg">
            {history.best_total_kg?.toFixed(1)} kg
          </div>
          <div className="text-zinc-500 text-xs">
            {history.meet_count} meets
            {history.rate_kg_per_month != null && (
              <span className="ml-2">
                {history.rate_kg_per_month >= 0 ? '+' : ''}
                {history.rate_kg_per_month.toFixed(1)} kg/mo
              </span>
            )}
          </div>
          {history.percentile_rank && (
            <div className="text-zinc-400 text-xs mt-0.5">
              <span className="text-zinc-200 font-medium">
                {history.percentile_rank.percentile.toFixed(0)}th
              </span>
              {' '}percentile of {history.percentile_rank.cohort_size.toLocaleString()}{' '}
              {history.percentile_rank.cohort_desc} lifters
            </div>
          )}
        </div>
      </div>

      {/* Weight class migration summary */}
      {history.weight_class_changes && history.weight_class_changes.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {history.weight_class_changes.map((c, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-zinc-900 border border-zinc-800 text-zinc-400"
            >
              {c.from_class} &rarr; {c.to_class}
              <span className="text-zinc-600">{fmtDate(c.date)}</span>
            </span>
          ))}
        </div>
      )}

      {/* QT proximity: how far from each qualifying standard */}
      {regionalsQt != null && history.best_total_kg != null && (
        <div className="flex flex-wrap gap-3 mb-3 text-xs">
          <span className="text-zinc-400">
            Regionals {ERA_LABEL[era]}:{' '}
            <span className={history.best_total_kg >= regionalsQt ? 'text-emerald-400' : 'text-orange-400'}>
              {history.best_total_kg >= regionalsQt
                ? `+${(history.best_total_kg - regionalsQt).toFixed(1)} kg above`
                : `${(regionalsQt - history.best_total_kg).toFixed(1)} kg below`}
            </span>
          </span>
          {nationalsQt != null && (
            <span className="text-zinc-400">
              Nationals {ERA_LABEL[era]}:{' '}
              <span className={history.best_total_kg >= nationalsQt ? 'text-emerald-400' : 'text-orange-400'}>
                {history.best_total_kg >= nationalsQt
                  ? `+${(history.best_total_kg - nationalsQt).toFixed(1)} kg above`
                  : `${(nationalsQt - history.best_total_kg).toFixed(1)} kg below`}
              </span>
            </span>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 mb-3 text-sm">
        <span className="text-zinc-400">QT era:</span>
        <div className="flex gap-1">
          {(['pre2025', '2025', '2027'] as const).map((e) => (
            <button
              key={e}
              onClick={() => setEra(e)}
              className={
                'px-2 py-1 rounded text-xs ' +
                (era === e
                  ? 'bg-zinc-700 text-zinc-100'
                  : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800')
              }
            >
              {ERA_LABEL[e]}
            </button>
          ))}
        </div>
        {regionalsQt && (
          <span className="text-zinc-500 text-xs">
            Regionals {regionalsQt.toFixed(1)} · Nationals {nationalsQt?.toFixed(1)}
          </span>
        )}
        {!regionalsQt && (
          <span className="text-zinc-500 text-xs">No QT for this class</span>
        )}
      </div>

      <div className="flex items-center gap-3 mb-3 text-sm">
        <span className="text-zinc-400">View:</span>
        <div className="flex gap-1">
          {(['total', 'per_lift'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setViewMode(m)}
              className={
                'px-2 py-1 rounded text-xs ' +
                (viewMode === m
                  ? 'bg-zinc-700 text-zinc-100'
                  : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800')
              }
            >
              {m === 'total' ? 'Total' : 'Squat / Bench / Deadlift'}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-3">
        <MethodPill variant="lifter-lookup" />
      </div>

      {nonSbdCount > 0 && (
        <p className="text-zinc-500 text-xs mb-2">
          Chart shows full-power (SBD) meets only. {nonSbdCount} other meet
          {nonSbdCount === 1 ? '' : 's'} (bench-only, push-pull, etc.)
          {' '}appear in the table below.
        </p>
      )}

      {!hasChartData ? (
        <div className="h-[200px] bg-zinc-900 rounded border border-zinc-800 p-6 flex items-center justify-center text-zinc-500 text-sm text-center">
          No full-power (SBD) meets for this lifter. See the table below for
          their bench-only or other meets.
        </div>
      ) : viewMode === 'per_lift' ? (
        <div className="h-80 md:h-[400px] bg-zinc-900 rounded border border-zinc-800 p-2">
          {isActive && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={perLiftChartData}
              margin={{ top: 8, right: 32, bottom: 36, left: 16 }}
            >
              <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                stroke="#a1a1aa"
                tickFormatter={(v) => fmtDateShort(String(v))}
                minTickGap={40}
                label={{
                  value: 'Date',
                  position: 'insideBottom',
                  offset: -16,
                  fill: '#a1a1aa',
                }}
              />
              <YAxis
                stroke="#a1a1aa"
                width={56}
                label={{
                  value: 'Best lift (kg)',
                  angle: -90,
                  position: 'insideLeft',
                  offset: 0,
                  fill: '#a1a1aa',
                  style: { textAnchor: 'middle' },
                }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#18181b',
                  border: '1px solid #3f3f46',
                  color: '#e4e4e7',
                }}
                formatter={(value) =>
                  typeof value === 'number' ? value.toFixed(1) + ' kg' : '—'
                }
                labelFormatter={(label) => fmtDate(String(label ?? ''))}
              />
              <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
              <Line
                type="monotone"
                dataKey="squat"
                name="Squat"
                stroke="#569cd6"
                strokeWidth={2}
                dot={{ r: 3, fill: '#569cd6' }}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="bench"
                name="Bench"
                stroke="#ce9178"
                strokeWidth={2}
                dot={{ r: 3, fill: '#ce9178' }}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="deadlift"
                name="Deadlift"
                stroke="#4ec9b0"
                strokeWidth={2}
                dot={{ r: 3, fill: '#4ec9b0' }}
                connectNulls
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          )}
        </div>
      ) : (
      <div className="h-80 md:h-[400px] bg-zinc-900 rounded border border-zinc-800 p-2">
        {isActive && (
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 32, bottom: 36, left: 16 }}>
            <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              stroke="#a1a1aa"
              tickFormatter={(v) => fmtDateShort(String(v))}
              minTickGap={40}
              label={{ value: 'Date', position: 'insideBottom', offset: -16, fill: '#a1a1aa' }}
            />
            <YAxis
              stroke="#a1a1aa"
              width={56}
              domain={[yMin, yMax]}
              label={{
                value: 'Total (kg)',
                angle: -90,
                position: 'insideLeft',
                offset: 0,
                fill: '#a1a1aa',
                style: { textAnchor: 'middle' },
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#18181b',
                border: '1px solid #3f3f46',
                color: '#e4e4e7',
              }}
              formatter={(value) =>
                typeof value === 'number' ? value.toFixed(1) + ' kg' : String(value ?? '—')
              }
              labelFormatter={(label) => fmtDate(String(label ?? ''))}
            />
            <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
            {regionalsQt && (
              <ReferenceLine
                y={regionalsQt}
                stroke="#94a3b8"
                strokeDasharray="4 4"
                label={{
                  value: `Regionals ${ERA_LABEL[era]} (${regionalsQt.toFixed(0)})`,
                  position: 'insideTopLeft',
                  fill: '#94a3b8',
                  fontSize: 11,
                  offset: 6,
                }}
              />
            )}
            {nationalsQt && (
              <ReferenceLine
                y={nationalsQt}
                stroke="#FB923C"
                strokeDasharray="4 4"
                label={{
                  value: `Nationals ${ERA_LABEL[era]} (${nationalsQt.toFixed(0)})`,
                  position: 'insideTopLeft',
                  fill: '#FB923C',
                  fontSize: 11,
                  offset: 6,
                }}
              />
            )}
            {/* Projection confidence band (renders behind lines) */}
            {history.projection && (
              <Area
                type="monotone"
                dataKey={(d: Record<string, unknown>) => {
                  const u = d.upper as number | null
                  const l = d.lower as number | null
                  if (u != null && l != null) return [l, u]
                  return null
                }}
                name="Projection band"
                fill="#4ec9b0"
                fillOpacity={0.1}
                stroke="none"
                legendType="rect"
                isAnimationActive={false}
              />
            )}
            <Line
              type="monotone"
              dataKey="total"
              name="Total"
              stroke="#569cd6"
              strokeWidth={2}
              dot={{ r: 4, fill: '#569cd6' }}
              connectNulls={false}
              isAnimationActive={false}
            />
            {history.projection && (
              <Line
                type="monotone"
                dataKey="projected"
                name="Projected"
                stroke="#4ec9b0"
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={{ r: 3, fill: '#4ec9b0' }}
                connectNulls={false}
                isAnimationActive={false}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
        )}
      </div>
      )}

      {/* Meet table. On phones we hide Class, Division, and S/B/D — Date +
          Meet + Event + Total + Δ is enough at small widths. The full table
          returns at sm:. The SBD triplet cell stays on a single line
          (whitespace-nowrap, LL2 fix 2026-04-26). For heavy lifters the meet
          name cell wraps instead — meet names are repeatable across rows and
          read fine on two lines, while a 3-line "270 / 175 / 285" stack of
          numbers reads as visual noise. */}
      <div className="mt-6">
        <table className="w-full text-sm">
          <thead className="text-zinc-400 text-xs uppercase tracking-wide">
            <tr className="border-b border-zinc-800">
              <th className="text-left py-2 pr-3 font-normal">Date</th>
              <th className="text-left py-2 pr-3 font-normal">Meet</th>
              <th className="text-left py-2 pr-2 font-normal">Event</th>
              <th className="text-left py-2 pr-3 font-normal hidden sm:table-cell">Class</th>
              <th className="text-left py-2 pr-3 font-normal hidden md:table-cell">Division</th>
              <th
                className="text-right py-2 pl-2 font-normal hidden sm:table-cell whitespace-nowrap"
                title="Squat / Bench / Deadlift (kg)"
              >
                Sq / Bp / Dl
              </th>
              <th className="text-right py-2 pl-2 font-normal">Total</th>
              <th
                className="text-right py-2 pl-2 font-normal hidden md:table-cell"
                title="IPF GL Points (Goodlift). Successor to IPF Points; Canadian lifters use this, not Dots."
              >
                GLP
              </th>
              <th
                className="text-right py-2 pl-2 font-normal hidden lg:table-cell whitespace-nowrap"
                title="Squat / Bench / Deadlift as % of total"
              >
                Sq / Bp / Dl %
              </th>
              <th className="text-right py-2 pl-2 font-normal">Δ first</th>
            </tr>
          </thead>
          <tbody className="text-zinc-200">
            {(() => {
              // Δ-first should be relative to the first SBD meet, since Total
              // means different things across event types. Non-SBD rows show
              // "—" for Δ-first.
              const firstSbdTotal = sbdMeets.length > 0 ? sbdMeets[0].TotalKg : null
              return history.meets.map((m, i) => {
                const isSbd = m.Event === 'SBD'
                const muted = !isSbd
                const rowClass = muted
                  ? 'border-b border-zinc-900 text-zinc-500'
                  : 'border-b border-zinc-900'
                const totalCellClass = muted
                  ? 'py-2 pl-2 text-right tabular-nums text-zinc-500'
                  : 'py-2 pl-2 text-right tabular-nums'
                const delta =
                  isSbd && firstSbdTotal != null && m.TotalKg != null
                    ? m.TotalKg - firstSbdTotal
                    : null
                return (
                  <tr key={i} className={rowClass}>
                    <td className="py-2 pr-3 whitespace-nowrap">{fmtDate(m.Date)}</td>
                    <td className="py-2 pr-3">{m.MeetName ?? '—'}</td>
                    <td
                      className="py-2 pr-2 whitespace-nowrap"
                      title={eventTitle(m.Event)}
                    >
                      <span
                        className={
                          'inline-block px-1.5 py-0.5 rounded text-xs font-mono ' +
                          (isSbd
                            ? 'bg-zinc-800 text-zinc-300'
                            : 'bg-zinc-900 text-zinc-500 border border-zinc-800')
                        }
                      >
                        {eventLabel(m.Event)}
                      </span>
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap hidden sm:table-cell">
                      {m.CanonicalWeightClass ? `${m.CanonicalWeightClass} kg` : '—'}
                      {m.class_changed && (
                        <ClassChangeBadge label="Weight class changed from previous meet" />
                      )}
                    </td>
                    <td className="py-2 pr-3 hidden md:table-cell">{m.Division ?? '—'}</td>
                    <td className="py-2 pl-2 text-right tabular-nums hidden sm:table-cell whitespace-nowrap">
                      {fmtSbd(m.Best3SquatKg, m.Best3BenchKg, m.Best3DeadliftKg)}
                    </td>
                    <td className={totalCellClass}>
                      {fmtKg(m.TotalKg)}
                      {m.is_pr && isSbd && (
                        <span className="ml-1 text-emerald-400 text-xs" title="Personal record">PR</span>
                      )}
                    </td>
                    <td className="py-2 pl-2 text-right tabular-nums text-zinc-500 hidden md:table-cell">
                      {fmtKg(m.Goodlift, 2)}
                    </td>
                    <td className="py-2 pl-2 text-right tabular-nums text-zinc-500 hidden lg:table-cell">
                      {m.TotalKg && m.Best3SquatKg && m.Best3BenchKg && m.Best3DeadliftKg
                        ? `${Math.round(100 * m.Best3SquatKg / m.TotalKg)}/${Math.round(100 * m.Best3BenchKg / m.TotalKg)}/${Math.round(100 * m.Best3DeadliftKg / m.TotalKg)}`
                        : '—'}
                    </td>
                    <td className="py-2 pl-2 text-right tabular-nums text-zinc-500">
                      {delta == null
                        ? '—'
                        : (delta >= 0 ? '+' : '') + delta.toFixed(1)}
                    </td>
                  </tr>
                )
              })
            })()}
          </tbody>
        </table>
      </div>
    </div>
  )
}
