// CompareView — multi-lifter trajectory comparison chart.
// Lazy-loaded from LifterLookup to keep it out of the initial bundle.

import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  CartesianGrid,
  Legend,
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
  const series = useMemo(() => {
    return compareNames.map((name, i) => {
      const data = queryData[i]
      const loading = queryLoading[i]
      const color = COMPARE_COLORS[i % COMPARE_COLORS.length]
      if (!data || !data.found) {
        return { name, color, points: [], loading, error: null }
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
  const xMax = hasData ? maxMonth + 1 : 12
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
          <div className="h-80 md:h-[480px] bg-zinc-900 rounded border border-zinc-800 p-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart margin={{ top: 8, right: 32, bottom: 36, left: 16 }}>
                <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
                <XAxis
                  type="number"
                  dataKey="months"
                  stroke="#a1a1aa"
                  domain={[0, xMax]}
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
                  contentStyle={{
                    backgroundColor: '#18181b',
                    border: '1px solid #3f3f46',
                    color: '#e4e4e7',
                  }}
                  formatter={(value) =>
                    typeof value === 'number' ? value.toFixed(1) + ' kg' : String(value ?? '—')
                  }
                  labelFormatter={(label) => `${label} months`}
                />
                <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
                {series.map((s) =>
                  s.points.length > 0 ? (
                    <Line
                      key={s.name}
                      data={s.points}
                      dataKey="total"
                      name={s.name}
                      stroke={s.color}
                      strokeWidth={2}
                      dot={{ r: 4, fill: s.color }}
                      isAnimationActive={false}
                    />
                  ) : null,
                )}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}
