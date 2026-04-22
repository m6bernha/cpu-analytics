// Athlete Projection (BETA) tab.
//
// Per-lift Engine C (Bayesian shrinkage + GLP-bracket cohort + Kaplan-Meier
// dropout correction) projection with a toggle for Engine D (MixedLM,
// currently delegates to shrinkage until the MixedLM wiring lands).
//
// Methodology lives on the About page (C6). The `<details>` block at the
// bottom of this tab is the short methodology note + link to About.

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
import {
  fetchAthleteProjection,
  fetchLifterSearch,
  type AthleteProjectionEngine,
  type AthleteProjectionLift,
  type AthleteProjectionResponse,
  type LifterSearchResult,
} from '../lib/api'

type LiftKey = 'total' | 'squat' | 'bench' | 'deadlift'

const HORIZONS = [3, 6, 12, 18] as const
const LIFTS: { key: LiftKey; label: string }[] = [
  { key: 'total', label: 'Total' },
  { key: 'squat', label: 'Squat' },
  { key: 'bench', label: 'Bench' },
  { key: 'deadlift', label: 'Deadlift' },
]

const COLORS = {
  history: '#569cd6',
  projected: '#ce9178',
  piBand: '#ce9178',
  reference: '#4ec9b0',
  grid: '#3f3f46',
}

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

export default function AthleteProjection({ isActive }: { isActive: boolean }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<LifterSearchResult | null>(null)
  const [engine, setEngine] = useState<AthleteProjectionEngine>('shrinkage')
  const [horizon, setHorizon] = useState<number>(12)
  const [liftKey, setLiftKey] = useState<LiftKey>('total')

  const debouncedQuery = useDebouncedValue(query, 300)

  const searchQuery = useQuery({
    queryKey: ['ap-search', debouncedQuery],
    queryFn: () => fetchLifterSearch(debouncedQuery, 12),
    enabled: debouncedQuery.trim().length >= 2 && !selected,
    staleTime: 5 * 60 * 1000,
  })

  const projectionQuery = useQuery({
    queryKey: ['ap-projection', selected?.Name, engine, horizon],
    queryFn: () =>
      fetchAthleteProjection(selected!.Name, engine, horizon, 6),
    enabled: !!selected && isActive,
    staleTime: 5 * 60 * 1000,
  })

  const resetSelection = () => {
    setSelected(null)
    setQuery('')
  }

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-zinc-100 text-lg font-semibold flex items-baseline gap-2">
          Athlete Projection
          <span className="text-amber-500 text-xs uppercase tracking-wide">
            Beta
          </span>
        </h2>
        <p className="text-zinc-400 text-sm mt-1 max-w-3xl">
          Pick a lifter, pick a horizon, see where their Squat, Bench, Deadlift,
          and Total are projected to land with a 95 percent prediction interval.
          Combines the lifter's own trajectory (Huber regression) with a cohort
          slope for their age division and IPF GL Points bracket.
        </p>
      </header>

      <SelectorPanel
        selected={selected}
        query={query}
        setQuery={setQuery}
        searchResults={searchQuery.data ?? []}
        searchIsLoading={searchQuery.isLoading && debouncedQuery.trim().length >= 2}
        onSelect={(r) => {
          setSelected(r)
          setQuery(r.Name)
        }}
        onReset={resetSelection}
        engine={engine}
        setEngine={setEngine}
        horizon={horizon}
        setHorizon={setHorizon}
        liftKey={liftKey}
        setLiftKey={setLiftKey}
      />

      {!selected && (
        <div className="mt-6 text-zinc-500 text-sm max-w-3xl">
          Start by searching a lifter above. The projection updates when you
          change engine, horizon, or lift.
        </div>
      )}

      {selected && projectionQuery.isLoading && (
        <div className="mt-6">
          <LoadingSkeleton lines={3} chart />
        </div>
      )}
      {selected && projectionQuery.isError && (
        <div className="mt-6">
          <QueryErrorCard
            error={projectionQuery.error as Error}
            onRetry={() => projectionQuery.refetch()}
          />
        </div>
      )}

      {selected && projectionQuery.data && projectionQuery.data.found && (
        <ResultPanel
          data={projectionQuery.data}
          liftKey={liftKey}
          horizon={horizon}
          isActive={isActive}
        />
      )}

      {selected && projectionQuery.data && !projectionQuery.data.found && (
        <div className="mt-6 p-4 border border-amber-900/40 bg-amber-950/20 rounded max-w-3xl text-amber-300 text-sm">
          No projection available: {projectionQuery.data.reason ?? 'unknown reason'}.
          A projection needs at least one SBD meet with age + bodyweight populated.
        </div>
      )}

      <MethodologyBlock />
    </div>
  )
}

// ---------- Selector panel (picker + engine + horizon + lift) ----------

function SelectorPanel({
  selected,
  query,
  setQuery,
  searchResults,
  searchIsLoading,
  onSelect,
  onReset,
  engine,
  setEngine,
  horizon,
  setHorizon,
  liftKey,
  setLiftKey,
}: {
  selected: LifterSearchResult | null
  query: string
  setQuery: (v: string) => void
  searchResults: LifterSearchResult[]
  searchIsLoading: boolean
  onSelect: (r: LifterSearchResult) => void
  onReset: () => void
  engine: AthleteProjectionEngine
  setEngine: (e: AthleteProjectionEngine) => void
  horizon: number
  setHorizon: (h: number) => void
  liftKey: LiftKey
  setLiftKey: (l: LiftKey) => void
}) {
  return (
    <section
      aria-label="Projection controls"
      className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_auto] gap-4 max-w-5xl"
    >
      <div>
        <label
          htmlFor="ap-search"
          className="text-zinc-300 text-xs uppercase tracking-wide block mb-1"
        >
          Lifter
        </label>
        {!selected ? (
          <div className="relative">
            <input
              id="ap-search"
              type="text"
              aria-label="Search lifter by name"
              placeholder="Start typing a name (min 2 chars)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
            />
            {query.trim().length >= 2 && (
              <div className="absolute top-full left-0 right-0 mt-1 max-h-72 overflow-y-auto bg-zinc-900 border border-zinc-800 rounded shadow-lg z-10">
                {searchIsLoading && (
                  <div className="px-3 py-2 text-zinc-500 text-sm">Searching...</div>
                )}
                {!searchIsLoading && searchResults.length === 0 && (
                  <div className="px-3 py-2 text-zinc-500 text-sm">No matches.</div>
                )}
                {searchResults.map((r) => (
                  <button
                    key={`${r.Name}-${r.LatestMeetDate}`}
                    type="button"
                    onClick={() => onSelect(r)}
                    className="w-full text-left px-3 py-2 hover:bg-zinc-800 border-b border-zinc-800 last:border-b-0"
                  >
                    <div className="text-zinc-100 text-sm">{r.Name}</div>
                    <div className="text-zinc-500 text-xs">
                      {r.Sex} · {r.LatestWeightClass} kg · {r.LatestEquipment} ·
                      {' '}{r.MeetCount} meet{r.MeetCount === 1 ? '' : 's'} · best{' '}
                      {Math.round(r.BestTotalKg)} kg
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <div className="flex-1 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded text-zinc-100 text-sm">
              {selected.Name}
              <span className="text-zinc-500 ml-2 text-xs">
                ({selected.Sex} · {selected.LatestWeightClass} kg ·{' '}
                {selected.LatestEquipment})
              </span>
            </div>
            <button
              type="button"
              onClick={onReset}
              className="px-3 py-2 text-zinc-400 text-xs hover:text-zinc-200 border border-zinc-700 rounded hover:bg-zinc-800"
            >
              Change
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        {/* Engine D (MixedLM) is not yet wired. The toggle renders only when
            the backend reports engine_d_available=true. Until then we ship
            Simple-only to avoid a toggle that silently falls back. */}
        {false && <EngineToggle engine={engine} setEngine={setEngine} />}
        <HorizonSelect horizon={horizon} setHorizon={setHorizon} />
        <LiftSelect liftKey={liftKey} setLiftKey={setLiftKey} />
      </div>
    </section>
  )
}

function EngineToggle({
  engine,
  setEngine,
}: {
  engine: AthleteProjectionEngine
  setEngine: (e: AthleteProjectionEngine) => void
}) {
  return (
    <div>
      <div className="text-zinc-300 text-xs uppercase tracking-wide mb-1">
        Engine
      </div>
      <div
        role="radiogroup"
        aria-label="Projection engine"
        className="inline-flex bg-zinc-900 border border-zinc-800 rounded overflow-hidden"
      >
        <button
          type="button"
          role="radio"
          aria-checked={engine === 'shrinkage'}
          onClick={() => setEngine('shrinkage')}
          className={
            'px-3 py-2 text-sm transition-colors ' +
            (engine === 'shrinkage'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-400 hover:text-zinc-200')
          }
        >
          Simple
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={engine === 'mixed_effects'}
          onClick={() => setEngine('mixed_effects')}
          className={
            'px-3 py-2 text-sm transition-colors ' +
            (engine === 'mixed_effects'
              ? 'bg-zinc-800 text-zinc-100'
              : 'text-zinc-400 hover:text-zinc-200')
          }
        >
          Advanced
        </button>
      </div>
    </div>
  )
}

function HorizonSelect({
  horizon,
  setHorizon,
}: {
  horizon: number
  setHorizon: (h: number) => void
}) {
  return (
    <div>
      <label
        htmlFor="ap-horizon"
        className="text-zinc-300 text-xs uppercase tracking-wide block mb-1"
      >
        Horizon
      </label>
      <select
        id="ap-horizon"
        value={horizon}
        onChange={(e) => setHorizon(Number(e.target.value))}
        className="px-3 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 focus:outline-none focus:border-zinc-500"
      >
        {HORIZONS.map((h) => (
          <option key={h} value={h}>
            {h} months
          </option>
        ))}
      </select>
    </div>
  )
}

function LiftSelect({
  liftKey,
  setLiftKey,
}: {
  liftKey: LiftKey
  setLiftKey: (l: LiftKey) => void
}) {
  return (
    <div>
      <div className="text-zinc-300 text-xs uppercase tracking-wide mb-1">
        Lift
      </div>
      <div
        role="radiogroup"
        aria-label="Lift to display"
        className="inline-flex bg-zinc-900 border border-zinc-800 rounded overflow-hidden"
      >
        {LIFTS.map((l) => (
          <button
            key={l.key}
            type="button"
            role="radio"
            aria-checked={liftKey === l.key}
            onClick={() => setLiftKey(l.key)}
            className={
              'px-3 py-2 text-sm transition-colors ' +
              (liftKey === l.key
                ? 'bg-zinc-800 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-200')
            }
          >
            {l.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------- Result panel (chart + info) ----------

function ResultPanel({
  data,
  liftKey,
  horizon,
  isActive,
}: {
  data: AthleteProjectionResponse
  liftKey: LiftKey
  horizon: number
  isActive: boolean
}) {
  const chartData = useMemo(
    () => buildChartData(data, liftKey),
    [data, liftKey],
  )

  const warningBanners = (
    <div className="flex flex-col gap-2 mb-3">
      {data.meta?.small_n_warning && (
        <Banner tone="amber">
          Fewer than 5 meets in this lifter's history. Projection is directionally
          informative only. Server clamped horizon to 6 months.
        </Banner>
      )}
      {data.meta?.long_horizon_warning && horizon > 12 && (
        <Banner tone="amber">
          Horizons past 12 months widen fast. Treat the 18-month band as the
          outer limit of plausibility, not a forecast.
        </Banner>
      )}
      {data.horizon_capped && !data.meta?.small_n_warning && (
        <Banner tone="zinc">
          Horizon capped server-side to {data.horizon_months} months.
        </Banner>
      )}
      {(data.outlier_lifts ?? []).length > 0 && (
        <Banner tone="amber">
          Most recent meet appears anomalous on{' '}
          <span className="font-medium">
            {(data.outlier_lifts ?? []).join(', ')}
          </span>
          . Projection uses the Huber-fit trend and best-of-last-3 current level.
        </Banner>
      )}
      {data.engine === 'mixed_effects' && data.meta?.engine_d_available === false && (
        <Banner tone="zinc">
          Advanced (MixedLM) engine wiring is still in progress. Numbers shown
          here are the Simple engine fallback.
        </Banner>
      )}
    </div>
  )

  return (
    <div className="mt-6">
      {warningBanners}

      <div className="h-[400px] sm:h-[480px]">
        {isActive && (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 16, right: 24, bottom: 8, left: 8 }}>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
              <XAxis
                dataKey="days"
                tick={{ fill: '#a1a1aa', fontSize: 12 }}
                label={{
                  value: 'Days from first meet',
                  position: 'insideBottom',
                  offset: -4,
                  fill: '#71717a',
                  fontSize: 11,
                }}
                type="number"
                domain={['auto', 'auto']}
              />
              <YAxis
                tick={{ fill: '#a1a1aa', fontSize: 12 }}
                label={{
                  value: `${liftLabel(liftKey)} (kg)`,
                  angle: -90,
                  position: 'insideLeft',
                  fill: '#71717a',
                  fontSize: 11,
                }}
                domain={['auto', 'auto']}
              />
              <Tooltip
                content={<ProjectionTooltip liftLabel={liftLabel(liftKey)} />}
              />
              <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
              <Area
                type="monotone"
                dataKey="piBand"
                name="95% prediction interval"
                fill={COLORS.piBand}
                fillOpacity={0.18}
                stroke="none"
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="projected"
                name="Projected"
                stroke={COLORS.projected}
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Scatter
                dataKey="history"
                name="Actual meets"
                fill={COLORS.history}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      <InfoPanel data={data} liftKey={liftKey} />
    </div>
  )
}

function Banner({
  tone,
  children,
}: {
  tone: 'amber' | 'zinc'
  children: React.ReactNode
}) {
  const cls =
    tone === 'amber'
      ? 'border-amber-900/40 bg-amber-950/20 text-amber-300'
      : 'border-zinc-800 bg-zinc-900/40 text-zinc-300'
  return (
    <div className={`p-3 border ${cls} rounded text-sm max-w-3xl`}>
      {children}
    </div>
  )
}

type ChartRow = {
  days: number
  history?: number
  projected?: number
  piBand?: [number, number]
}

function liftLabel(liftKey: LiftKey): string {
  switch (liftKey) {
    case 'total':
      return 'Total'
    case 'squat':
      return 'Squat'
    case 'bench':
      return 'Bench'
    case 'deadlift':
      return 'Deadlift'
  }
}

function buildChartData(
  data: AthleteProjectionResponse,
  liftKey: LiftKey,
): ChartRow[] {
  const rows: ChartRow[] = []

  if (liftKey === 'total') {
    for (const h of data.total_history ?? []) {
      rows.push({ days: h.days_from_first, history: h.total_kg })
    }
    const last = data.total_history?.[data.total_history.length - 1]
    if (last) {
      rows.push({
        days: last.days_from_first,
        projected: last.total_kg,
        piBand: [last.total_kg, last.total_kg],
      })
    }
    for (const p of data.total_projected_points ?? []) {
      rows.push({
        days: p.days_from_first,
        projected: p.projected_kg,
        piBand: [p.lower_kg, p.upper_kg],
      })
    }
  } else {
    const lift = data.lifts?.[liftKey]
    if (!lift) return rows
    // Per-lift history dots come from the response's `lift.history` (one
    // entry per meet that contested this lift). The x-axis is days_from_first
    // relative to the lifter's first meet of this lift, matching the scale
    // used by projected_points.
    const liftHistory = lift.history ?? []
    if (liftHistory.length > 0) {
      for (const h of liftHistory) {
        rows.push({ days: h.days_from_first, history: h.kg })
      }
      // Seed the projection line at the last historical point so the chart
      // joins history to projection without a visual gap.
      const last = liftHistory[liftHistory.length - 1]
      rows.push({
        days: last.days_from_first,
        projected: last.kg,
        piBand: [last.kg, last.kg],
      })
    } else if (lift.current_level != null && lift.last_meet_day != null) {
      // Fallback for responses that predate the history field.
      rows.push({
        days: lift.last_meet_day,
        history: lift.current_level,
        projected: lift.current_level,
        piBand: [lift.current_level, lift.current_level],
      })
    }
    for (const p of lift.projected_points) {
      rows.push({
        days: p.days_from_first,
        projected: p.projected_kg,
        piBand: [p.lower_kg, p.upper_kg],
      })
    }
  }
  rows.sort((a, b) => a.days - b.days)
  return rows
}

function ProjectionTooltip({
  active,
  payload,
  label,
  liftLabel,
}: {
  active?: boolean
  payload?: Array<{ payload?: ChartRow }>
  label?: number | string
  liftLabel: string
}) {
  if (!active || !payload || payload.length === 0) return null
  const row = payload[0].payload as ChartRow | undefined
  if (!row) return null
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-xs text-zinc-200">
      <div className="text-zinc-400">Day {Math.round(Number(label ?? 0))}</div>
      {row.history != null && (
        <div>
          <span className="text-zinc-400">{liftLabel}: </span>
          <span className="text-zinc-100 font-medium">{row.history.toFixed(1)} kg</span>
        </div>
      )}
      {row.projected != null && (
        <div>
          <span className="text-zinc-400">Projected: </span>
          <span className="text-zinc-100 font-medium">{row.projected.toFixed(1)} kg</span>
        </div>
      )}
      {row.piBand && row.piBand[0] !== row.piBand[1] && (
        <div className="text-zinc-500">
          PI: [{row.piBand[0].toFixed(1)}, {row.piBand[1].toFixed(1)}]
        </div>
      )}
    </div>
  )
}

function InfoPanel({
  data,
  liftKey,
}: {
  data: AthleteProjectionResponse
  liftKey: LiftKey
}) {
  const bracket = data.meta?.lifter_bracket
  const liftRow = liftKey === 'total' ? null : data.lifts?.[liftKey]

  return (
    <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 max-w-4xl">
      <InfoCard title="Cohort">
        {bracket ? (
          <>
            <Row label="Age division" value={data.age_division ?? '-'} />
            <Row label="GLP bracket" value={bracket.bracket} />
            <Row label="GLP score" value={bracket.glp_score?.toFixed(1) ?? '-'} />
            <Row
              label="Cohort size"
              value={`${bracket.n_cell} lifter${bracket.n_cell === 1 ? '' : 's'}`}
            />
            {bracket.merged_from.length > 0 && (
              <Row
                label="Merged with"
                value={bracket.merged_from.filter((b) => b !== bracket.bracket).join(', ') || '-'}
              />
            )}
            {bracket.is_global_fallback && (
              <div className="text-xs text-amber-400 mt-1">
                Division has sparse data; using division-global slope.
              </div>
            )}
          </>
        ) : (
          <div className="text-zinc-500 text-xs">Cohort info unavailable.</div>
        )}
      </InfoCard>

      <InfoCard title="Shrinkage">
        {liftRow ? (
          <>
            <Row label="Meets contested" value={String(liftRow.n_meets)} />
            <Row
              label="Personal weight"
              value={`${Math.round(liftRow.w_personal * 100)}%`}
            />
            <Row
              label="Cohort weight"
              value={`${Math.round((1 - liftRow.w_personal) * 100)}%`}
            />
            <Row
              label="Current level"
              value={
                liftRow.current_level != null
                  ? `${liftRow.current_level.toFixed(1)} kg`
                  : '-'
              }
            />
            <Row
              label="Rate"
              value={
                liftRow.slope_combined_kg_per_month != null
                  ? `${liftRow.slope_combined_kg_per_month.toFixed(2)} kg/mo`
                  : '-'
              }
            />
          </>
        ) : (
          <PerLiftShrinkageSummary data={data} />
        )}
      </InfoCard>

      <InfoCard title="Uncertainty">
        <Row
          label="K-M multiplier"
          value={data.meta?.km_multiplier.toFixed(2) ?? '-'}
        />
        <Row
          label="K-M sample"
          value={
            data.meta?.km_sample_size != null
              ? `${data.meta.km_sample_size} lifters`
              : '-'
          }
        />
        <Row
          label="Bracket transitions"
          value={String(data.meta?.bracket_transitions ?? 0)}
        />
        <Row
          label="As of"
          value={data.as_of_date ?? '-'}
        />
      </InfoCard>
    </div>
  )
}

function PerLiftShrinkageSummary({ data }: { data: AthleteProjectionResponse }) {
  if (!data.lifts) return <div className="text-zinc-500 text-xs">-</div>
  return (
    <div className="space-y-1.5 text-xs">
      {(['squat', 'bench', 'deadlift'] as const).map((k) => {
        const l = data.lifts![k] as AthleteProjectionLift
        return (
          <div key={k} className="flex justify-between gap-4">
            <span className="text-zinc-400 capitalize">{k}</span>
            <span className="text-zinc-200">
              n={l.n_meets} · w<sub>p</sub>={Math.round(l.w_personal * 100)}%
              {l.slope_combined_kg_per_month != null && (
                <> · {l.slope_combined_kg_per_month.toFixed(2)} kg/mo</>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function InfoCard({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="p-3 bg-zinc-900/40 border border-zinc-800 rounded">
      <div className="text-zinc-300 text-xs uppercase tracking-wide mb-2">
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between text-xs gap-2">
      <span className="text-zinc-400">{label}</span>
      <span className="text-zinc-200 font-medium">{value}</span>
    </div>
  )
}

// ---------- Methodology `<details>` block (pattern per CLAUDE.md) ----------

function MethodologyBlock() {
  return (
    <details className="mt-8 max-w-3xl">
      <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
        Methodology and caveats
      </summary>
      <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
        <p>
          <span className="text-zinc-400 font-medium">Engine C (Simple):</span>{' '}
          Bayesian shrinkage combines the lifter's own Huber-robust slope with
          a cohort slope from their age division and IPF GL Points bracket.
          Weight on personal history grows with meet count as w<sub>p</sub>{' '}
          = n / (n + 5). Level is never shrunk, only slope.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Engine D (Advanced):</span>{' '}
          Mixed-effects model with random intercept + slope per lifter, fixed
          effects for age division and GLP bracket. Advanced is currently a
          placeholder that delegates to Simple; MixedLM wiring ships in a
          follow-up release.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Prediction interval:</span>{' '}
          Shown band is a 95 percent prediction interval for where this
          specific lifter's next meet total could land, not a confidence
          interval for the fit. It widens quadratically with horizon and is
          inflated by a Kaplan-Meier dropout multiplier on the cohort term.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Horizon caps:</span> 18
          months hard cap. Lifters with fewer than 5 meets are capped at 6
          months. A loud warning fires past 12 months.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">What is not modelled:</span>{' '}
          Weight class changes, raw-to-equipped transitions, injury gaps,
          meet-day performance on specific dates, training quality, or coaching.
          Projection is a cohort baseline, not a prediction of your next result.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Attribution:</span>{' '}
          Cohort stratification approach follows coach Sean Yen's input.
          Full methodology will live on the About page.
        </p>
      </div>
    </details>
  )
}
