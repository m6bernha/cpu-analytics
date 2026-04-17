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

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useUrlState } from '../lib/useUrlState'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchFilters,
  fetchLiftProgression,
  fetchProgression,
  type FiltersResponse,
  type LiftProgressionResponse,
  type ProgressionResponse,
} from '../lib/api'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'

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
  max_gap_months: string
  same_class_only: string
  per_lift: string
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
  max_gap_months: '',
  same_class_only: '',
  per_lift: '',
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
            {o === '' ? 'Off' : o}
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
        max_gap_months: filters.max_gap_months || undefined,
        same_class_only: filters.same_class_only === 'true' ? 'true' : undefined,
      }),
    enabled: filtersQuery.isSuccess && filters.per_lift !== 'true',
  })

  // Per-lift progression (S/B/D curves) when the toggle is on.
  // Same filters flow through so changing any filter updates per-lift view.
  const liftProgQuery = useQuery<LiftProgressionResponse>({
    queryKey: ['lift-progression', filters],
    queryFn: () =>
      fetchLiftProgression({
        sex: filters.sex,
        equipment: filters.equipment,
        tested: filters.tested,
        event: filters.event,
        weight_class: filters.weight_class,
        division: filters.division,
        x_axis: filters.x_axis,
      }),
    enabled: filtersQuery.isSuccess && filters.per_lift === 'true',
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
        // +/- 1 standard deviation band
        stdBand: [p.y - p.std, p.y + p.std] as [number, number],
        lifter_count: p.lifter_count,
        trend_y: trend ? trend.slope * p.x + trend.intercept : null,
      }))
  }, [progQuery.data])

  const update = (patch: Partial<FilterState>) => setFilters(patch)

  const f = filtersQuery.data

  // Mobile: collapse the filter panel behind a toggle, since 8 dropdowns on a
  // phone dominate the first screen. Desktop (`md:`): always show expanded.
  const [filtersOpenMobile, setFiltersOpenMobile] = useState(false)

  const filterSummary = useMemo(() => {
    const bits = [
      filters.sex,
      filters.weight_class,
      filters.equipment,
      filters.event,
      filters.max_gap_months ? `<${filters.max_gap_months}mo gap` : '',
    ].filter(Boolean)
    return bits.join(' · ')
  }, [filters])

  return (
    <div className="flex flex-col md:flex-row gap-6">
      {/* ---- Filter panel ---- */}
      <aside className="w-full md:w-64 md:shrink-0">
        <div className="flex items-center justify-between mb-3 md:block">
          <h2 className="text-zinc-200 text-sm font-semibold">Filters</h2>
          <button
            type="button"
            onClick={() => setFiltersOpenMobile((v) => !v)}
            className="md:hidden text-xs text-zinc-400 hover:text-zinc-200 px-2 py-1 rounded border border-zinc-800 bg-zinc-900"
            aria-expanded={filtersOpenMobile}
          >
            {filtersOpenMobile ? 'Hide' : `Show · ${filterSummary}`}
          </button>
        </div>
        <div className={(filtersOpenMobile ? 'block' : 'hidden') + ' md:block'}>
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
              options={f.division}
              onChange={(v) => update({ division: v })}
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
              label="Exclude gaps longer than"
              value={filters.max_gap_months}
              options={['', '6', '12', '18', '24', '36']}
              onChange={(v) => update({ max_gap_months: v })}
              hint="Excludes lifters with any inter-meet gap longer than N months (comeback filter)."
            />
            <label className="flex items-center gap-2 mb-3 cursor-pointer">
              <input
                type="checkbox"
                checked={filters.same_class_only === 'true'}
                onChange={(e) =>
                  update({ same_class_only: e.target.checked ? 'true' : '' })
                }
                className="accent-zinc-400"
              />
              <span className="text-zinc-300 text-xs uppercase tracking-wide">Same class only</span>
            </label>
            <label className="flex items-center gap-2 mb-3 cursor-pointer">
              <input
                type="checkbox"
                checked={filters.per_lift === 'true'}
                onChange={(e) =>
                  update({ per_lift: e.target.checked ? 'true' : '' })
                }
                className="accent-zinc-400"
              />
              <span className="text-zinc-300 text-xs uppercase tracking-wide">
                Per-lift (Squat / Bench / Deadlift)
              </span>
            </label>
            <Select
              label="X axis"
              value={filters.x_axis}
              options={f.x_axis}
              onChange={(v) => update({ x_axis: v })}
            />
          </>
        )}
        </div>
      </aside>

      {/* ---- Chart area ---- */}
      <section className="flex-1 min-w-0">
        <div className="mb-4">
          <h2 className="text-zinc-100 text-lg font-semibold">Cohort progression</h2>
          <p className="text-zinc-500 text-sm">
            Average change in total from each lifter's first meet in the selected cohort.
          </p>
        </div>

        {filters.per_lift === 'true' && liftProgQuery.isLoading && (
          <div className="text-zinc-500 text-sm">Loading per-lift progression…</div>
        )}
        {filters.per_lift === 'true' && liftProgQuery.error && (
          <div className="text-red-400 text-sm">
            Lift progression failed: {(liftProgQuery.error as Error).message}
          </div>
        )}
        {filters.per_lift === 'true' && liftProgQuery.data && (
          <>
            <div className="text-sm text-zinc-400 mb-2">
              <span className="text-zinc-200 tabular-nums">
                {liftProgQuery.data.n_lifters.toLocaleString()}
              </span>{' '}
              lifters with complete Squat / Bench / Deadlift data at every meet
            </div>
            {(filters.age_category !== 'All' ||
              filters.max_gap_months !== '' ||
              filters.same_class_only === 'true') && (
              <div className="text-amber-500 text-xs mb-2">
                Note: the per-lift view currently ignores Age category, Gap
                filter, and Same-class-only. Total view respects all filters.
              </div>
            )}
            <div className="h-80 md:h-[480px] bg-zinc-900 rounded border border-zinc-800 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  margin={{ top: 8, right: 32, bottom: 36, left: 4 }}
                >
                  <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    stroke="#a1a1aa"
                    domain={[0, 'auto']}
                    label={{
                      value: liftProgQuery.data.x_label,
                      position: 'insideBottom',
                      offset: -16,
                      fill: '#a1a1aa',
                    }}
                  />
                  <YAxis
                    stroke="#a1a1aa"
                    width={56}
                    label={{
                      value: 'Change from first meet (kg)',
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
                      typeof value === 'number' ? value.toFixed(2) + ' kg' : String(value ?? '—')
                    }
                  />
                  <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
                  <Line
                    data={liftProgQuery.data.lifts.squat}
                    type="monotone"
                    dataKey="y"
                    name="Squat"
                    stroke="#569cd6"
                    strokeWidth={2}
                    dot={{ r: 2, fill: '#569cd6' }}
                    isAnimationActive={false}
                  />
                  <Line
                    data={liftProgQuery.data.lifts.bench}
                    type="monotone"
                    dataKey="y"
                    name="Bench"
                    stroke="#ce9178"
                    strokeWidth={2}
                    dot={{ r: 2, fill: '#ce9178' }}
                    isAnimationActive={false}
                  />
                  <Line
                    data={liftProgQuery.data.lifts.deadlift}
                    type="monotone"
                    dataKey="y"
                    name="Deadlift"
                    stroke="#4ec9b0"
                    strokeWidth={2}
                    dot={{ r: 2, fill: '#4ec9b0' }}
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
        {filters.per_lift !== 'true' && progQuery.isLoading && (
          <LoadingSkeleton lines={3} chart />
        )}
        {filters.per_lift !== 'true' && progQuery.isError && (
          <QueryErrorCard
            error={progQuery.error}
            onRetry={() => progQuery.refetch()}
            label="Progression"
          />
        )}

        {filters.per_lift !== 'true' && progQuery.data && progQuery.data.points.length === 0 && (
          <div className="text-zinc-500 text-sm">
            No data for this filter combination. Try loosening one of the filters.
          </div>
        )}

        {filters.per_lift !== 'true' && progQuery.data && progQuery.data.points.length > 0 && (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-zinc-400 mb-2">
              <div>
                <span className="text-zinc-200 tabular-nums">{progQuery.data.n_lifters.toLocaleString()}</span> of{' '}
                <span className="text-zinc-200 tabular-nums">{progQuery.data.n_all_lifters.toLocaleString()}</span> lifters
                <span className="text-zinc-500 ml-1">
                  ({progQuery.data.n_all_lifters > 0
                    ? `${Math.round(100 * progQuery.data.n_lifters / progQuery.data.n_all_lifters)}% returned for 2+ meets`
                    : 'no lifters in scope'})
                </span>
              </div>
              <div>
                <span className="text-zinc-200 tabular-nums">{progQuery.data.n_meets.toLocaleString()}</span> meets
              </div>
              {progQuery.data.avg_first_total != null && (
                <div>
                  Avg first total: <span className="text-zinc-200 tabular-nums">{progQuery.data.avg_first_total.toFixed(1)} kg</span>
                  <span className="text-zinc-500 ml-1">(all lifters incl. one-and-done)</span>
                </div>
              )}
              {progQuery.data.trend && (
                <div>
                  Trend:{' '}
                  <span className="text-zinc-200 tabular-nums">
                    {progQuery.data.trend.slope >= 0 ? '+' : ''}
                    {progQuery.data.trend.slope.toFixed(3)} kg/{progQuery.data.trend.unit}
                  </span>
                  <span className="text-zinc-500 ml-2">
                    R<sup>2</sup> = {progQuery.data.trend.r_squared.toFixed(3)}
                  </span>
                </div>
              )}
            </div>

            {/* Age data loss indicator */}
            {filters.age_category !== 'All' &&
              progQuery.data.n_lifters_before_age_filter > progQuery.data.n_lifters && (
              <div className="text-zinc-500 text-xs mb-2">
                Showing {progQuery.data.n_lifters.toLocaleString()} of{' '}
                {progQuery.data.n_lifters_before_age_filter.toLocaleString()} lifters.{' '}
                {Math.round(
                  100 * (1 - progQuery.data.n_lifters / progQuery.data.n_lifters_before_age_filter)
                )}
                % dropped because the Age column is missing for their meet rows.
              </div>
            )}

            <div className="h-80 md:h-[480px] bg-zinc-900 rounded border border-zinc-800 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartData} margin={{ top: 8, right: 24, bottom: 36, left: 4 }}>
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
                    width={56}
                    label={{
                      value: 'Change from first meet (kg)',
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
                    formatter={(value, name) => {
                      const n = typeof value === 'number' ? value : Number(value)
                      if (!Number.isFinite(n)) return ['—', name]
                      return [n.toFixed(2) + ' kg', name]
                    }}
                    labelFormatter={(label) =>
                      `${progQuery.data?.x_label}: ${String(label ?? '')}`
                    }
                  />
                  <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
                  <Area
                    type="monotone"
                    dataKey="stdBand"
                    name="+/- 1 SD"
                    fill="#569cd6"
                    fillOpacity={0.1}
                    stroke="none"
                    legendType="rect"
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="y"
                    name="Mean change"
                    stroke="#569cd6"
                    strokeWidth={2}
                    dot={{ r: 2, fill: '#569cd6' }}
                    activeDot={{ r: 5 }}
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
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            {/* Survivorship bias + methodology notes */}
            <details className="mt-3 max-w-2xl">
              <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
                Methodology notes
              </summary>
              <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
                <p>
                  <span className="text-zinc-400 font-medium">Survivorship bias:</span> Only
                  lifters with 2+ meets appear in this chart. Lifters who competed once and
                  quit are excluded, which biases the curve toward people who improved enough
                  to keep competing. The shaded band shows +/- 1 standard deviation of the
                  underlying data at each point.
                </p>
                <p>
                  <span className="text-zinc-400 font-medium">Population thinning:</span> At
                  higher x-values, fewer lifters remain (because most careers are short). The
                  tail of the curve reflects only the most persistent competitors and should
                  not be read as a prediction for all lifters.
                </p>
                <p>
                  <span className="text-zinc-400 font-medium">Trendline:</span> Ordinary
                  least-squares linear fit on x-values with 5+ distinct lifters, weighted by lifter count so dense early years dominate the slope.
                  R-squared measures how well the line fits the averaged points, not
                  individual lifter trajectories.
                </p>
              </div>
            </details>
          </>
        )}
      </section>
    </div>
  )
}
