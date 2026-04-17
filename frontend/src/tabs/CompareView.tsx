// CompareView - multi-lifter trajectory comparison chart.
// Lazy-loaded from LifterLookup to keep it out of the initial bundle.

import { useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchLifterHistory,
  type LifterSearchResult,
} from '../lib/api'

export const COMPARE_COLORS = ['#569cd6', '#ce9178', '#4ec9b0', '#c586c0']
export const MAX_COMPARE = 4

type SeriesPoint = {
  months: number
  total: number | null
  date: string
  meet: string
}

type Series = {
  name: string
  color: string
  points: SeriesPoint[]
  loading: boolean
  noSbd?: boolean
}

type XRange = 'all' | '6' | '12' | '24' | '60'

const X_RANGE_LABELS: Record<XRange, string> = {
  all: 'All',
  '6': '6mo',
  '12': '1y',
  '24': '2y',
  '60': '5y',
}

// A meet is "near" the hover x if it sits within this many months. At 3
// months two meets a quarter apart still get listed together; further out
// the schedules between lifters are real gaps and we suppress those rather
// than implying a value we don't have.
const TOOLTIP_THRESHOLD_MONTHS = 3

function CompareTooltipContent({
  active,
  label,
  series,
}: {
  active?: boolean
  label?: number | string
  series: Series[]
}) {
  if (!active || label == null || label === '') return null
  const x = Number(label)
  if (!Number.isFinite(x)) return null

  type Match = { name: string; color: string; point: SeriesPoint }
  const matches: Match[] = []
  for (const s of series) {
    let best: SeriesPoint | null = null
    let bestDiff = Infinity
    for (const p of s.points) {
      if (p.total == null) continue
      const diff = Math.abs(p.months - x)
      if (diff < bestDiff) {
        bestDiff = diff
        best = p
      }
    }
    if (best && bestDiff <= TOOLTIP_THRESHOLD_MONTHS) {
      matches.push({ name: s.name, color: s.color, point: best })
    }
  }
  if (matches.length === 0) return null

  return (
    <div
      style={{
        backgroundColor: '#18181b',
        border: '1px solid #3f3f46',
        color: '#e4e4e7',
        padding: '8px 12px',
        fontSize: 12,
        lineHeight: 1.4,
        minWidth: 180,
      }}
    >
      <div style={{ color: '#a1a1aa', marginBottom: 4 }}>
        Near month {Math.round(x)}
      </div>
      {matches.map((m) => (
        <div
          key={m.name}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '2px 0',
          }}
        >
          <span
            style={{
              display: 'inline-block',
              width: 8,
              height: 8,
              backgroundColor: m.color,
              borderRadius: 2,
              flexShrink: 0,
            }}
          />
          <span style={{ color: m.color, fontWeight: 500 }}>{m.name}</span>
          <span
            style={{
              color: '#e4e4e7',
              fontVariantNumeric: 'tabular-nums',
              marginLeft: 'auto',
            }}
          >
            {m.point.total != null ? m.point.total.toFixed(1) + ' kg' : '—'}
          </span>
          <span style={{ color: '#71717a', fontSize: 10 }}>
            (mo {m.point.months})
          </span>
        </div>
      ))}
    </div>
  )
}

export default function CompareView({
  compareNames,
  addCompare,
  removeCompare,
  query,
  setQuery,
  debouncedQuery,
  searchResults,
  searchIsFetching,
  searchError,
}: {
  compareNames: string[]
  addCompare: (name: string) => void
  removeCompare: (name: string) => void
  query: string
  setQuery: (q: string) => void
  debouncedQuery: string
  searchResults: LifterSearchResult[] | undefined
  searchIsFetching: boolean
  searchError: unknown
}) {
  const [xRange, setXRange] = useState<XRange>('all')

  const historyQueries = useQueries({
    queries: compareNames.map((name) => ({
      queryKey: ['lifter-history', name],
      queryFn: () => fetchLifterHistory(name),
      enabled: !!name,
    })),
  })

  // Stable deps for useMemo: historyQueries is a new array ref every render,
  // so we extract the stable parts (data objects + loading flags).
  const queryData = historyQueries.map((q) => q.data)
  const queryLoading = historyQueries.map((q) => q.isLoading)

  // Each lifter's trajectory is re-anchored to months-from-their-own-first-SBD-meet
  // so the comparison is about progression rate, not calendar alignment.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const series: Series[] = useMemo(() => {
    return compareNames.map((name, i) => {
      const data = queryData[i]
      const loading = queryLoading[i]
      const color = COMPARE_COLORS[i % COMPARE_COLORS.length]
      if (!data || !data.found) {
        return { name, color, points: [], loading }
      }
      const sbd = data.meets.filter((m) => m.Event === 'SBD')
      if (sbd.length === 0) {
        return { name, color, points: [], loading: false, noSbd: true }
      }
      const firstDays = sbd[0].DaysFromFirst
      return {
        name,
        color,
        loading: false,
        points: sbd.map((m) => ({
          months: Math.round((m.DaysFromFirst - firstDays) / 30.44),
          total: m.TotalKg,
          date: m.Date,
          meet: m.MeetName ?? '',
        })),
      }
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compareNames.join(','), ...queryData, ...queryLoading])

  // Use reduce instead of Math.min(...arr) to avoid the ~100K JS argument
  // limit when a lifter has thousands of meets.
  const allTotals = series
    .flatMap((s) => s.points.map((p) => p.total))
    .filter((t): t is number => t != null)
  const allMonths = series.flatMap((s) => s.points.map((p) => p.months))
  const hasData = allTotals.length > 0
  const minTotal = hasData ? allTotals.reduce((a, b) => (a < b ? a : b), Infinity) : 0
  const maxTotal = hasData ? allTotals.reduce((a, b) => (a > b ? a : b), -Infinity) : 100
  const maxMonth = allMonths.reduce((a, b) => (a > b ? a : b), 0)
  const yMin = hasData ? Math.floor((minTotal - 25) / 25) * 25 : 0
  const yMax = hasData ? Math.ceil((maxTotal + 25) / 25) * 25 : 100

  // Career length per lifter (last meet's months value), used for the
  // mismatch hint that nudges users toward the range toggle.
  const careerLengths = series
    .map((s) => (s.points.length > 0 ? s.points[s.points.length - 1].months : 0))
    .filter((m) => m > 0)
  const minCareer = careerLengths.length > 0
    ? careerLengths.reduce((a, b) => (a < b ? a : b), Infinity)
    : 0
  const maxCareer = careerLengths.reduce((a, b) => (a > b ? a : b), 0)
  // Below 4x the dot effect isn't really happening; above it the short
  // lifter looks like a single dot in the All view.
  const careerMismatch =
    careerLengths.length >= 2 && minCareer > 0 && maxCareer >= 4 * minCareer

  // Effective x-axis maximum honors the user's range pick. When 'all' is
  // active we show the full data range; otherwise the chart is clamped to
  // the chosen window so short careers aren't crushed against the y-axis.
  const xMaxData = hasData ? maxMonth + 1 : 12
  const xMax = xRange === 'all' ? xMaxData : Number(xRange)

  // Filter each lifter's points to within the visible range. The custom
  // tooltip then reads from this filtered set, so it never offers a meet
  // beyond the visible window.
  const visibleSeries: Series[] = useMemo(() => {
    return series.map((s) => ({
      ...s,
      points: s.points.filter((p) => p.months <= xMax),
    }))
  }, [series, xMax])

  // One row per integer month gives the tooltip a place to anchor at every
  // hover position. Lifter columns are null on months without a meet; the
  // Line's connectNulls bridges the gap visually.
  const combinedData = useMemo(() => {
    if (!hasData) return []
    const rows: Array<Record<string, number | null>> = []
    for (let m = 0; m <= xMax; m++) {
      const row: Record<string, number | null> = { months: m }
      visibleSeries.forEach((s, i) => {
        const point = s.points.find((p) => p.months === m)
        row[`lifter_${i}`] = point && point.total != null ? point.total : null
      })
      rows.push(row)
    }
    return rows
  }, [visibleSeries, xMax, hasData])

  const anyLoading = historyQueries.some((q) => q.isLoading)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left pane: chips + search */}
      <div className="lg:col-span-1">
        {compareNames.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-2">
            {series.map((s) => (
              <span
                key={s.name}
                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border"
                style={{ borderColor: s.color }}
              >
                <span style={{ color: s.color }}>●</span>
                <span className="text-zinc-200">{s.name}</span>
                <button
                  onClick={() => removeCompare(s.name)}
                  className="ml-1 text-zinc-500 hover:text-red-400"
                  aria-label={`Remove ${s.name}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {compareNames.length < MAX_COMPARE ? (
          <>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Add lifter (${compareNames.length}/${MAX_COMPARE})`}
              aria-label="Add lifter to comparison by name"
              className="w-full px-4 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
            />
            <div className="mt-4">
              {query.trim().length > 0 && query.trim().length < 2 && (
                <p className="text-zinc-500 text-sm">Type at least 2 characters.</p>
              )}
              {searchIsFetching && debouncedQuery.trim().length >= 2 && (
                <p className="text-zinc-500 text-sm">Searching…</p>
              )}
              {searchError != null && (
                <p className="text-red-400 text-sm">
                  Error: {(searchError as Error).message}
                </p>
              )}
              {searchResults && searchResults.length === 0 && !searchIsFetching && (
                <p className="text-zinc-500 text-sm">No lifters match that name.</p>
              )}
              {searchResults && searchResults.length > 0 && (
                <ul className="divide-y divide-zinc-800">
                  {searchResults.map((lifter) => {
                    const already = compareNames.includes(lifter.Name)
                    return (
                      <li key={lifter.Name}>
                        <button
                          onClick={() => {
                            if (!already) {
                              addCompare(lifter.Name)
                              setQuery('')
                            }
                          }}
                          disabled={already}
                          className={
                            'w-full text-left py-2 px-2 -mx-2 rounded transition-colors ' +
                            (already
                              ? 'opacity-40 cursor-not-allowed'
                              : 'hover:bg-zinc-900')
                          }
                        >
                          <div className="text-zinc-100 text-sm">
                            {lifter.Name}
                            {already && (
                              <span className="text-zinc-500 text-xs ml-2">(added)</span>
                            )}
                          </div>
                          <div className="text-zinc-500 text-xs mt-0.5">
                            {lifter.Sex} · {lifter.LatestWeightClass} kg ·{' '}
                            {lifter.BestTotalKg.toFixed(1)} kg · {lifter.MeetCount} meets
                          </div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </>
        ) : (
          <p className="text-zinc-500 text-xs">
            Max {MAX_COMPARE} lifters per comparison. Remove one to add another.
          </p>
        )}
      </div>

      {/* Right pane: chart */}
      <div className="lg:col-span-2">
        {compareNames.length === 0 ? (
          <div className="text-zinc-500 text-sm">
            Add lifters from the search at left to compare their SBD trajectories.
            Each lifter's curve starts at month 0 (their own first full-power meet)
            so you're comparing progression rates, not calendar dates.
          </div>
        ) : !hasData && anyLoading ? (
          <div className="text-zinc-500 text-sm">Loading trajectories…</div>
        ) : !hasData ? (
          <div className="text-zinc-500 text-sm">
            None of the selected lifters have SBD meets in the dataset.
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
              <span className="text-zinc-400">X-axis:</span>
              <div className="flex gap-1 flex-wrap">
                {(['all', '6', '12', '24', '60'] as const).map((r) => (
                  <button
                    key={r}
                    onClick={() => setXRange(r)}
                    className={
                      'px-2 py-1 rounded text-xs ' +
                      (xRange === r
                        ? 'bg-zinc-700 text-zinc-100'
                        : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200 border border-zinc-800')
                    }
                  >
                    {X_RANGE_LABELS[r]}
                  </button>
                ))}
              </div>
            </div>

            {careerMismatch && xRange === 'all' && (
              <p className="text-amber-400 text-xs mb-2">
                Career lengths vary by {Math.round(maxCareer / minCareer)}x. Pick a
                smaller range above to compare progression rates side by side.
              </p>
            )}

            <div className="flex flex-wrap gap-x-3 gap-y-1 mb-2 px-1">
              {visibleSeries.map((s) =>
                s.points.length > 0 ? (
                  <span
                    key={s.name}
                    className="inline-flex items-center gap-1.5 text-xs"
                  >
                    <span
                      className="inline-block w-3.5 h-3.5 rounded-sm"
                      style={{ backgroundColor: s.color }}
                      aria-hidden="true"
                    />
                    <span className="text-zinc-200">{s.name}</span>
                  </span>
                ) : null,
              )}
            </div>

            <div className="h-80 md:h-[480px] bg-zinc-900 rounded border border-zinc-800 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={combinedData}
                  margin={{ top: 8, right: 32, bottom: 36, left: 16 }}
                >
                  <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    dataKey="months"
                    stroke="#a1a1aa"
                    domain={[0, xMax]}
                    allowDataOverflow
                    label={{
                      value: 'Months from first SBD meet',
                      position: 'insideBottom',
                      offset: -16,
                      fill: '#a1a1aa',
                    }}
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
                    cursor={{ stroke: '#52525b', strokeDasharray: '3 3' }}
                    content={(props: { active?: boolean; label?: number | string }) => (
                      <CompareTooltipContent
                        active={props.active}
                        label={props.label}
                        series={visibleSeries}
                      />
                    )}
                  />
                  {visibleSeries.map((s, i) =>
                    s.points.length > 0 ? (
                      <Line
                        key={s.name}
                        type="monotone"
                        dataKey={`lifter_${i}`}
                        name={s.name}
                        stroke={s.color}
                        strokeWidth={2}
                        dot={{ r: 4, fill: s.color }}
                        connectNulls
                        isAnimationActive={false}
                      />
                    ) : null,
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
