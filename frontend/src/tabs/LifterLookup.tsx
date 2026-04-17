// Lifter Lookup tab (M6).
//
// Two-pane layout:
//   - Left: name search with debounced input (~M3 search behaviour)
//   - Right: detail view for a selected lifter, OR a manual entry form
//
// The lifter trajectory is fetched from /api/lifters/{name}/history. This is
// independent of any cohort filter elsewhere in the app — a Junior or Master
// lifter looking themselves up will always see their own data here regardless
// of how the QT or Progression tabs are scoped.
//
// QT reference lines come from /api/qt/standards. The line set displayed
// depends on the lifter's latest_weight_class. The era toggle switches between
// 2025 and 2027 standards.

import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useUrlState } from '../lib/useUrlState'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
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
import {
  fetchLifterHistory,
  fetchLifterSearch,
  fetchQtStandards,
  postManualTrajectory,
  type LifterHistory,
  type LifterMeet,
  type LifterSearchResult,
  type ManualEntry,
  type QtStandardRow,
} from '../lib/api'

// ---------- Debounce hook ----------

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
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

// ---------- Lifter detail subcomponent ----------

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

function LifterDetail({
  history,
  standards,
}: {
  history: LifterHistory
  standards: QtStandardRow[] | undefined
}) {
  const [era, setEra] = useState<Era>('2025')
  const [viewMode, setViewMode] = useState<'total' | 'per_lift'>('total')

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
        </div>
      ) : (
      <div className="h-80 md:h-[400px] bg-zinc-900 rounded border border-zinc-800 p-2">
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
                stroke="#ce9178"
                strokeDasharray="4 4"
                label={{
                  value: `Nationals ${ERA_LABEL[era]} (${nationalsQt.toFixed(0)})`,
                  position: 'insideTopLeft',
                  fill: '#ce9178',
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
      </div>
      )}

      {/* Meet table. On phones we hide Class, Division, and S/B/D — Date +
          Meet + Event + Total + Δ is enough at small widths. The full table
          returns at sm:. */}
      <div className="mt-6 overflow-x-auto">
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
                Sq / Bn / Dl
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
                Sq / Bn / Dl %
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
                        <span className="ml-1 text-amber-400 text-xs" title="Weight class changed from previous meet">
                          &#9650;
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 hidden md:table-cell">{m.Division ?? '—'}</td>
                    <td className="py-2 pl-2 text-right tabular-nums whitespace-nowrap hidden sm:table-cell">
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
                    <td className="py-2 pl-2 text-right tabular-nums text-zinc-500 hidden lg:table-cell whitespace-nowrap">
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

// ---------- Manual entry form ----------

type ManualFormRow = {
  date: string
  total: string
  weight_class: string
  meet_name: string
}

const EMPTY_ROW: ManualFormRow = { date: '', total: '', weight_class: '', meet_name: '' }

function ManualEntryForm({
  onSubmit,
  pending,
  result,
  error,
  standards,
}: {
  onSubmit: (req: { sex: string; rows: ManualFormRow[] }) => void
  pending: boolean
  result: LifterHistory | null
  error: Error | null
  standards: QtStandardRow[] | undefined
}) {
  const [sex, setSex] = useState<'M' | 'F'>('M')
  const [rows, setRows] = useState<ManualFormRow[]>([
    { ...EMPTY_ROW },
    { ...EMPTY_ROW },
    { ...EMPTY_ROW },
  ])

  const updateRow = (i: number, patch: Partial<ManualFormRow>) =>
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))

  const addRow = () => setRows((prev) => [...prev, { ...EMPTY_ROW }])
  const removeRow = (i: number) =>
    setRows((prev) => (prev.length > 1 ? prev.filter((_, idx) => idx !== i) : prev))

  const validRows = rows.filter((r) => r.date && r.total && Number(r.total) > 0)
  const canSubmit = validRows.length >= 1

  return (
    <div>
      <h3 className="text-zinc-100 text-lg font-semibold mb-1">Manual entry</h3>
      <p className="text-zinc-500 text-sm mb-4">
        Enter your meets below if you're not in the OpenIPF dataset, or to project a
        hypothetical trajectory.
      </p>

      <div className="mb-3">
        <label className="text-zinc-300 text-xs uppercase tracking-wide block mb-1">Sex</label>
        <select
          value={sex}
          onChange={(e) => setSex(e.target.value as 'M' | 'F')}
          className="px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 focus:outline-none focus:border-zinc-500"
        >
          <option value="M">M</option>
          <option value="F">F</option>
        </select>
      </div>

      {/* Desktop: one row per meet in a wide table. */}
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-zinc-400 text-xs uppercase tracking-wide">
            <tr className="border-b border-zinc-800">
              <th className="text-left py-2 pr-2 font-normal">Date</th>
              <th className="text-left py-2 pr-2 font-normal">Total (kg)</th>
              <th className="text-left py-2 pr-2 font-normal">Class</th>
              <th className="text-left py-2 pr-2 font-normal">Meet name</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-zinc-900">
                <td className="py-1 pr-2">
                  <input
                    type="date"
                    value={r.date}
                    onChange={(e) => updateRow(i, { date: e.target.value })}
                    className="w-full px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={r.total}
                    onChange={(e) => updateRow(i, { total: e.target.value })}
                    placeholder="0.0"
                    className="w-24 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="text"
                    value={r.weight_class}
                    onChange={(e) => updateRow(i, { weight_class: e.target.value })}
                    placeholder="83"
                    className="w-16 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="text"
                    value={r.meet_name}
                    onChange={(e) => updateRow(i, { meet_name: e.target.value })}
                    placeholder="(optional)"
                    className="w-full px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm"
                  />
                </td>
                <td className="py-1 pl-2">
                  <button
                    onClick={() => removeRow(i)}
                    disabled={rows.length === 1}
                    className="text-zinc-500 hover:text-red-400 disabled:opacity-30 text-sm"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: one card per meet. The four columns don't fit side-by-side
          at phone widths, so we stack them in a grid that still keeps Date
          and Total on the same row (the two fields users always fill). */}
      <div className="sm:hidden space-y-3">
        {rows.map((r, i) => (
          <div
            key={i}
            className="border border-zinc-800 rounded p-3 bg-zinc-900/50 relative"
          >
            <button
              onClick={() => removeRow(i)}
              disabled={rows.length === 1}
              className="absolute top-2 right-2 text-zinc-500 hover:text-red-400 disabled:opacity-30 text-lg leading-none px-2 py-1"
              aria-label="Remove meet"
            >
              ×
            </button>
            <div className="text-zinc-500 text-xs mb-2">Meet #{i + 1}</div>
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Date
                </span>
                <input
                  type="date"
                  value={r.date}
                  onChange={(e) => updateRow(i, { date: e.target.value })}
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Total (kg)
                </span>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={r.total}
                  onChange={(e) => updateRow(i, { total: e.target.value })}
                  placeholder="0.0"
                  inputMode="decimal"
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                />
              </label>
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Class
                </span>
                <input
                  type="text"
                  value={r.weight_class}
                  onChange={(e) => updateRow(i, { weight_class: e.target.value })}
                  placeholder="83"
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Meet name
                </span>
                <input
                  type="text"
                  value={r.meet_name}
                  onChange={(e) => updateRow(i, { meet_name: e.target.value })}
                  placeholder="(optional)"
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm"
                />
              </label>
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2 mt-3">
        <button
          onClick={addRow}
          className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-100 text-sm rounded border border-zinc-700"
        >
          Add row
        </button>
        <button
          onClick={() => onSubmit({ sex, rows: validRows })}
          disabled={!canSubmit || pending}
          className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 text-zinc-100 text-sm rounded border border-zinc-600"
        >
          {pending ? 'Computing…' : 'Compute trajectory'}
        </button>
      </div>

      {error && (
        <div className="mt-3 text-red-400 text-sm">Error: {error.message}</div>
      )}

      {result && (
        <div className="mt-6">
          <LifterDetail history={result} standards={standards} />
        </div>
      )}
    </div>
  )
}

// CompareView is lazy-loaded: it pulls in its own Recharts + useQueries
// and only ships to clients who actually open the Compare tab.
const CompareView = lazy(() => import('./CompareView'))

// ---------- Tab component ----------

// Duplicated from CompareView to avoid a static import that would pull
// the lazy chunk back into the main bundle.
const MAX_COMPARE = 4

type Mode = 'search' | 'compare' | 'manual'


const MODE_LABELS: Record<Mode, string> = {
  search: 'Search',
  compare: 'Compare',
  manual: 'Manual entry',
}

function parseMode(raw: string): Mode {
  if (raw === 'manual' || raw === 'compare') return raw
  return 'search'
}

function parseLifters(raw: string): string[] {
  if (!raw) return []
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, MAX_COMPARE)
}

export default function LifterLookup() {
  // URL state covers all shareable lookup views:
  //   ?tab=lookup                                  -> search, nothing selected
  //   ?tab=lookup&lifter=Matthias%20Bernhard       -> deep-link to a lifter
  //   ?tab=lookup&mode=compare&lifters=A,B,C       -> multi-lifter comparison
  //   ?tab=lookup&mode=manual                      -> manual trajectory form
  const [urlState, setUrlState] = useUrlState({
    mode: 'search',
    lifter: '',
    lifters: '',
  })
  const mode: Mode = parseMode(urlState.mode)
  const selectedName: string | null = urlState.lifter ? urlState.lifter : null
  const compareNames: string[] = useMemo(
    () => parseLifters(urlState.lifters),
    [urlState.lifters],
  )
  const setMode = (m: Mode) => {
    setUrlState({ mode: m })
    setQuery('')  // clear stale search text when switching modes
  }
  const setSelectedName = (name: string | null) =>
    setUrlState({ lifter: name ?? '' })
  const setCompareNames = (names: string[]) =>
    setUrlState({ lifters: names.slice(0, MAX_COMPARE).join(',') })
  const addCompare = (name: string) => {
    if (compareNames.includes(name)) return
    if (compareNames.length >= MAX_COMPARE) return
    setCompareNames([...compareNames, name])
  }
  const removeCompare = (name: string) =>
    setCompareNames(compareNames.filter((n) => n !== name))

  // Search query stays as ephemeral local state — URL-backing every keystroke
  // would flood history.
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebouncedValue(query, 300)

  const searchQuery = useQuery<LifterSearchResult[]>({
    queryKey: ['lifter-search', debouncedQuery],
    queryFn: () => fetchLifterSearch(debouncedQuery),
    enabled: debouncedQuery.trim().length >= 2,
  })

  const historyQuery = useQuery<LifterHistory>({
    queryKey: ['lifter-history', selectedName],
    queryFn: () => fetchLifterHistory(selectedName!),
    enabled: !!selectedName,
  })

  const standardsQuery = useQuery<QtStandardRow[]>({
    queryKey: ['qt-standards'],
    queryFn: fetchQtStandards,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const manualMutation = useMutation<LifterHistory, Error, { sex: string; rows: ManualFormRow[] }>({
    mutationFn: async ({ sex, rows }) => {
      const entries: ManualEntry[] = rows.map((r) => ({
        date: r.date,
        total_kg: Number(r.total),
        weight_class: r.weight_class || null,
        meet_name: r.meet_name || null,
      }))
      return postManualTrajectory({ name: '(manual entry)', sex, entries })
    },
  })

  return (
    <div>
      <div className="mb-4 flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-3">
        <div>
          <h2 className="text-zinc-100 text-lg font-semibold">Lifter lookup</h2>
          <p className="text-zinc-500 text-sm">
            Search any Canadian lifter in the CPU/IPF dataset, or enter your meets manually
            to project a trajectory. Lifters who share the same name in the OpenPowerlifting
            database may show merged histories.
          </p>
        </div>
        <div
          className="flex gap-2 shrink-0 -mx-1 px-1 overflow-x-auto"
          role="tablist"
          aria-label="Lifter Lookup mode"
        >
          {(['search', 'compare', 'manual'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              role="tab"
              aria-selected={mode === m}
              className={
                'px-3 py-1.5 rounded text-sm transition-colors whitespace-nowrap ' +
                (mode === m
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
              }
            >
              {MODE_LABELS[m]}
            </button>
          ))}
        </div>
      </div>

      {mode === 'search' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left pane: search */}
          <div className="lg:col-span-1">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a name"
              aria-label="Search lifters by name"
              className="w-full px-4 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              // autoFocus removed: on phones it pops the keyboard and pushes content down
            />

            <div className="mt-4">
              {query.trim().length > 0 && query.trim().length < 2 && (
                <p className="text-zinc-500 text-sm">Type at least 2 characters.</p>
              )}
              {searchQuery.isFetching && debouncedQuery.trim().length >= 2 && (
                <p className="text-zinc-500 text-sm">Searching…</p>
              )}
              {searchQuery.error && (
                <p className="text-red-400 text-sm">
                  Error: {(searchQuery.error as Error).message}
                </p>
              )}
              {searchQuery.data && searchQuery.data.length === 0 && !searchQuery.isFetching && (
                <p className="text-zinc-500 text-sm">No lifters match that name.</p>
              )}
              {searchQuery.data && searchQuery.data.length > 0 && (
                <>
                  <ul className="divide-y divide-zinc-800">
                    {searchQuery.data.map((lifter) => (
                      <li key={lifter.Name}>
                        <button
                          onClick={() => setSelectedName(lifter.Name)}
                          className={
                            'w-full text-left py-2 px-2 -mx-2 rounded hover:bg-zinc-900 transition-colors ' +
                            (selectedName === lifter.Name ? 'bg-zinc-900' : '')
                          }
                        >
                          <div className="text-zinc-100 text-sm">{lifter.Name}</div>
                          <div className="text-zinc-500 text-xs mt-0.5">
                            {lifter.Sex} · {lifter.LatestWeightClass} kg ·{' '}
                            {lifter.BestTotalKg.toFixed(1)} kg · {lifter.MeetCount} meets
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {searchQuery.data.length >= 25 && (
                    <p className="text-zinc-600 text-xs mt-3">
                      Showing top {searchQuery.data.length} by best total. If you don't see
                      yourself, type more of your name.
                    </p>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Right pane: detail */}
          <div className="lg:col-span-2">
            {!selectedName && (
              <div className="text-zinc-500 text-sm">
                Select a lifter from the search results to see their trajectory and
                qualifying total comparison.
              </div>
            )}
            {selectedName && (
              <button
                onClick={() => setSelectedName(null)}
                className="lg:hidden text-zinc-400 hover:text-zinc-200 text-xs mb-3 flex items-center gap-1"
              >
                <span aria-hidden="true">&larr;</span> Back to results
              </button>
            )}
            {selectedName && historyQuery.isLoading && (
              <LoadingSkeleton lines={3} chart />
            )}
            {historyQuery.isError && (
              <QueryErrorCard
                error={historyQuery.error}
                onRetry={() => historyQuery.refetch()}
                label="Lifter history"
              />
            )}
            {historyQuery.data && historyQuery.data.found && (
              <LifterDetail history={historyQuery.data} standards={standardsQuery.data} />
            )}
            {historyQuery.data && !historyQuery.data.found && (
              <div className="text-zinc-500 text-sm">No history found for {selectedName}.</div>
            )}
          </div>
        </div>
      )}

      {mode === 'compare' && (
        <Suspense fallback={<div className="text-zinc-500 text-sm">Loading compare view...</div>}>
          <CompareView
            compareNames={compareNames}
            addCompare={addCompare}
            removeCompare={removeCompare}
            query={query}
            setQuery={setQuery}
            debouncedQuery={debouncedQuery}
            searchResults={searchQuery.data}
            searchIsFetching={searchQuery.isFetching}
            searchError={searchQuery.error}
          />
        </Suspense>
      )}

      {mode === 'manual' && (
        <ManualEntryForm
          onSubmit={(req) => manualMutation.mutate(req)}
          pending={manualMutation.isPending}
          result={manualMutation.data ?? null}
          error={(manualMutation.error as Error | null) ?? null}
          standards={standardsQuery.data}
        />
      )}
    </div>
  )
}
