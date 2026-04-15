// Progression tab (M4).
//
// Cohort progression over time. Filter controls on the left, chart on the right.
// Fetches /api/filters once on mount for dropdown values, then refetches
// /api/cohort/progression whenever any filter changes.
//
// The chart shows two lines:
//   - mean TotalDiffFromFirst at each x-value (blue)
//   - linear trendline fit on points with >= 5 lifters (orange, dashed)
// The trendline is computed client-side from slope/intercept returned by the
// backend, so it spans the full x range and doesn't wiggle through noise.

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useUrlState } from '../lib/useUrlState'
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
  fetchFilters,
  fetchProgression,
  type FiltersResponse,
  type ProgressionResponse,
} from '../lib/api'

// ---------- Filter state ----------

type FilterState = {
  sex: string
  weight_class: string
  equipment: string
  tested: string
  event: string
  division: string
  age_category: string
  x_axis: string
}

const DEFAULT_FILTERS: FilterState = {
  sex: 'M',
  weight_class: 'Overall',
  equipment: 'Raw',
  tested: 'Yes',
  event: 'SBD',
  division: 'Open',
  age_category: 'All',
  x_axis: 'Years',
}

// Minimum lifters a point needs to be worth plotting. Below this the chart
// gets dominated by singleton outliers in the long tail (e.g. one lifter
// making +200 kg after 14 years). Trend already uses a stricter threshold
// (5) defined in the backend.
const MIN_LIFTERS_FOR_POINT = 2

// ---------- Small UI helpers ----------

function Select({
  label,
  value,
  options,
  onChange,
  hint,
}: {
  label: string
  value: string
  options: string[]
  onChange: (v: string) => void
  hint?: string
}) {
  return (
    <label className="block mb-3">
      <div className="text-zinc-300 text-xs uppercase tracking-wide mb-1">{label}</div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 focus:outline-none focus:border-zinc-500"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
      {hint && <div className="text-zinc-500 text-xs mt-1">{hint}</div>}
    </label>
  )
}

// ---------- Component ----------

export default function Progression() {
  const [filters, setFilters] = useUrlState<FilterState>(DEFAULT_FILTERS)

  // Filter enum values for dropdowns. Fetched once on mount.
  // staleTime is 10 min (not Infinity) so that if the first fetch happens
  // during a backend cold-start race and returns bad data, the next navigation
  // back to this tab will refetch and self-correct.
  const filtersQuery = useQuery<FiltersResponse>({
    queryKey: ['filters'],
    queryFn: fetchFilters,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  // Cohort progression data. Refetches whenever any filter changes.
  const progQuery = useQuery<ProgressionResponse>({
    queryKey: ['progression', filters],
    queryFn: () =>
      fetchProgression({
        sex: filters.sex,
        equipment: filters.equipment,
        tested: filters.tested,
        event: filters.event,
        weight_class: filters.weight_class,
        division: filters.division,
        age_category: filters.age_category,
        x_axis: filters.x_axis,
      }),
    enabled: filtersQuery.isSuccess,
  })

  // Weight class options depend on sex. "Overall" is always first.
  const weightClassOptions = useMemo<string[]>(() => {
    const f = filtersQuery.data
    if (!f) return ['Overall']
    const bySex = f.weight_class[filters.sex as 'M' | 'F'] ?? []
    return ['Overall', ...bySex]
  }, [filtersQuery.data, filters.sex])

  // Merge API data with client-computed trendline y-values for Recharts.
  // Recharts draws the trendline as a separate series across the same x values.
  // We drop x-values that represent fewer than MIN_LIFTERS_FOR_POINT distinct
  // lifters so the chart isn't dragged around by singletons in the long tail.
  const chartData = useMemo(() => {
    const prog = progQuery.data
    if (!prog) return []
    const trend = prog.trend
    return prog.points
      .filter((p) => p.lifter_count >= MIN_LIFTERS_FOR_POINT)
      .map((p) => ({
        x: p.x,
        y: p.y,
        lifter_count: p.lifter_count,
        trend_y: trend ? trend.slope * p.x + trend.intercept : null,
      }))
  }, [progQuery.data])

  const update = (patch: Partial<FilterState>) => setFilters(patch)

  const f = filtersQuery.data

  return (
    <div className="flex gap-6">
      {/* ---- Filter panel ---- */}
      <aside className="w-64 shrink-0">
        <h2 className="text-zinc-200 text-sm font-semibold mb-3">Filters</h2>
        {filtersQuery.isLoading && (
          <div className="text-zinc-500 text-sm">
            Loading filters…
            <div className="text-zinc-600 text-xs mt-1">
              First visit after a while can take up to ~50 s while the server wakes up.
            </div>
          </div>
        )}
        {filtersQuery.error && (
          <div className="text-red-400 text-sm">
            Filter load failed: {(filtersQuery.error as Error).message}
          </div>
        )}
        {f && (
          <>
            <Select
              label="Sex"
              value={filters.sex}
              options={f.sex}
              onChange={(v) => update({ sex: v, weight_class: 'Overall' })}
            />
            <Select
              label="Weight class"
              value={filters.weight_class}
              options={weightClassOptions}
              onChange={(v) => update({ weight_class: v })}
            />
            <Select
              label="Equipment"
              value={filters.equipment}
              options={f.equipment}
              onChange={(v) => update({ equipment: v })}
            />
            {/* Tested filter intentionally hidden: the OpenIPF export is IPF-only,
                so every row already has Tested='Yes'. Showing a single-option
                dropdown is just noise. The filter value is still sent to the API
                so widening scope later is a one-line change. */}
            <Select
              label="Event"
              value={filters.event}
              options={f.event}
              onChange={(v) => update({ event: v })}
            />
            <Select
              label="Division"
              value={filters.division}
              options={['Any', 'Open', 'Juniors', 'Sub-Juniors', 'Masters 1', 'Masters 2', 'Masters 3', 'Masters 4']}
              onChange={(v) => update({ division: v === 'Any' ? '' : v })}
              hint="Division is federation-free-text. 'Open' is what CPU uses."
            />
            <Select
              label="Age category (numeric)"
              value={filters.age_category}
              options={f.age_category}
              onChange={(v) => update({ age_category: v })}
              hint="Uses the Age column, which is ~70% NULL. Many lifters drop out if set."
            />
            <Select
              label="X axis"
              value={filters.x_axis}
              options={f.x_axis}
              onChange={(v) => update({ x_axis: v })}
            />
          </>
        )}
      </aside>

      {/* ---- Chart area ---- */}
      <section className="flex-1 min-w-0">
        <div className="mb-4">
          <h2 className="text-zinc-100 text-lg font-semibold">Cohort progression</h2>
          <p className="text-zinc-500 text-sm">
            Average change in total from each lifter's first meet in the selected cohort.
          </p>
        </div>

        {progQuery.isLoading && (
          <div className="text-zinc-500 text-sm">
            Loading progression…
            <div className="text-zinc-600 text-xs mt-1">
              First visit after a while can take up to ~50 s while the server wakes up.
            </div>
          </div>
        )}
        {progQuery.error && (
          <div className="text-red-400 text-sm">
            Progression load failed: {(progQuery.error as Error).message}
          </div>
        )}

        {progQuery.data && progQuery.data.points.length === 0 && (
          <div className="text-zinc-500 text-sm">
            No data for this filter combination. Try loosening one of the filters.
          </div>
        )}

        {progQuery.data && progQuery.data.points.length > 0 && (
          <>
            <div className="flex gap-6 text-sm text-zinc-400 mb-2">
              <div>
                <span className="text-zinc-200 tabular-nums">{progQuery.data.n_lifters.toLocaleString()}</span> lifters
              </div>
              <div>
                <span className="text-zinc-200 tabular-nums">{progQuery.data.n_meets.toLocaleString()}</span> meets
              </div>
              {progQuery.data.trend && (
                <div>
                  Trend:{' '}
                  <span className="text-zinc-200 tabular-nums">
                    {progQuery.data.trend.slope >= 0 ? '+' : ''}
                    {progQuery.data.trend.slope.toFixed(3)} kg/{progQuery.data.trend.unit}
                  </span>
                </div>
              )}
            </div>

            <div className="h-[480px] bg-zinc-900 rounded border border-zinc-800 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 16, right: 32, bottom: 48, left: 16 }}>
                  <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
                  <XAxis
                    dataKey="x"
                    stroke="#a1a1aa"
                    label={{
                      value: progQuery.data.x_label,
                      position: 'insideBottom',
                      offset: -16,
                      fill: '#a1a1aa',
                    }}
                  />
                  <YAxis
                    stroke="#a1a1aa"
                    label={{
                      value: 'Change from first meet (kg)',
                      angle: -90,
                      position: 'insideLeft',
                      offset: 10,
                      fill: '#a1a1aa',
                    }}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#18181b',
                      border: '1px solid #3f3f46',
                      color: '#e4e4e7',
                    }}
                    formatter={(value, name) => {
                      const n = typeof value === 'number' ? value : Number(value)
                      if (!Number.isFinite(n)) return ['—', name]
                      return [n.toFixed(2) + ' kg', name]
                    }}
                    labelFormatter={(label) =>
                      `${progQuery.data?.x_label}: ${String(label ?? '')}`
                    }
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="y"
                    name="Mean change"
                    stroke="#569cd6"
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="linear"
                    dataKey="trend_y"
                    name={
                      progQuery.data.trend
                        ? `Trend (${progQuery.data.trend.slope.toFixed(3)} kg/${progQuery.data.trend.unit})`
                        : 'Trend'
                    }
                    stroke="#ce9178"
                    strokeDasharray="6 4"
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
