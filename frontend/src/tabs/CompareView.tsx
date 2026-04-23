// CompareView - multi-lifter trajectory comparison chart.
// Lazy-loaded from LifterLookup to keep it out of the initial bundle.

import { useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
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
  fetchQtStandards,
  type LifterHistory,
  type LifterSearchResult,
  type QtStandardRow,
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

// ---------- Inline helpers (not imported from LifterDetail) ----------

const MONTHS_ABBR = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

// Parse ISO yyyy-mm-dd without going through Date() to avoid UTC/local drift.
function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parts = iso.slice(0, 10).split('-').map(Number)
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso
  const [y, m, d] = parts
  return `${MONTHS_ABBR[m - 1]} ${d}, ${y}`
}

// Count distinct IPF weight classes across all meets.
function classMigrationCount(history: LifterHistory): number {
  const classes = new Set<string>()
  for (const m of history.meets) {
    if (m.CanonicalWeightClass) classes.add(m.CanonicalWeightClass)
  }
  return classes.size
}

// First SBD meet date string (ISO).
function firstSbdDate(history: LifterHistory): string | null {
  for (const m of history.meets) {
    if (m.Event === 'SBD') return m.Date
  }
  return null
}

// SBD meet count.
function sbdMeetCount(history: LifterHistory): number {
  return history.meets.filter((m) => m.Event === 'SBD').length
}

// Find regionals + nationals rows for a given sex + weight class.
function findQtRows(
  standards: QtStandardRow[] | undefined,
  sex: string | undefined,
  weightClass: string | null | undefined,
): { regionals?: QtStandardRow; nationals?: QtStandardRow } {
  if (!standards || !sex || !weightClass) return {}
  const matches = standards.filter(
    (s) => s.Sex === sex && s.WeightClass === weightClass,
  )
  return {
    regionals: matches.find((r) => r.Level === 'Regionals'),
    nationals: matches.find((r) => r.Level === 'Nationals'),
  }
}

// QT era config used for the four reference lines and status chips.
type QtEraKey = 'QT_pre2025' | 'QT_2025' | 'QT_2027'

type QtChip = {
  label: string
  level: 'Regionals' | 'Nationals'
  field: QtEraKey
  // Muted stroke color for reference lines so they don't overpower lifter lines.
  stroke: string
}

const QT_CHIPS: QtChip[] = [
  { label: 'Reg 2025', level: 'Regionals', field: 'QT_2025', stroke: '#6b7280' },
  { label: 'Reg 2027', level: 'Regionals', field: 'QT_2027', stroke: '#4b5563' },
  { label: 'Nat 2025', level: 'Nationals', field: 'QT_2025', stroke: '#78716c' },
  { label: 'Nat 2027', level: 'Nationals', field: 'QT_2027', stroke: '#57534e' },
]

// ---------- Tooltip ----------

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

// ---------- Per-lifter summary card ----------

function LifterCard({
  name,
  color,
  history,
  standards,
}: {
  name: string
  color: string
  history: LifterHistory | undefined
  standards: QtStandardRow[] | undefined
}) {
  if (!history || !history.found) {
    return (
      <div
        className="rounded border bg-zinc-900 p-3 text-xs text-zinc-500"
        style={{ borderColor: color }}
      >
        <div className="font-medium mb-1" style={{ color }}>
          {name}
        </div>
        Loading…
      </div>
    )
  }

  const sbd = sbdMeetCount(history)
  const first = firstSbdDate(history)
  const classMigrations = classMigrationCount(history)
  const bestTotal = history.best_total_kg
  const rate = history.rate_kg_per_month

  const sex = history.sex
  const latestClass = history.latest_weight_class
  const { regionals, nationals } = findQtRows(standards, sex, latestClass)

  // For each chip: did the lifter's best total clear this threshold?
  function chipHit(chip: QtChip): boolean | null {
    if (bestTotal == null) return null
    const row = chip.level === 'Regionals' ? regionals : nationals
    const qt = row?.[chip.field]
    if (qt == null) return null
    return bestTotal >= qt
  }

  return (
    <div
      className="rounded border bg-zinc-900 p-3 text-xs"
      style={{ borderColor: color }}
    >
      {/* Name */}
      <div className="font-semibold text-sm mb-2 truncate" style={{ color }}>
        {name}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 mb-2">
        <div className="text-zinc-400">Best total</div>
        <div className="text-zinc-100 tabular-nums text-right">
          {bestTotal != null ? bestTotal.toFixed(1) + ' kg' : '—'}
        </div>

        <div className="text-zinc-400">Rate</div>
        <div className="text-zinc-100 tabular-nums text-right">
          {rate != null
            ? (rate >= 0 ? '+' : '') + rate.toFixed(1) + ' kg/mo'
            : '—'}
        </div>

        <div className="text-zinc-400">SBD meets</div>
        <div className="text-zinc-100 tabular-nums text-right">{sbd}</div>

        <div className="text-zinc-400">First SBD</div>
        <div className="text-zinc-100 text-right">{fmtDate(first)}</div>

        <div className="text-zinc-400">Classes</div>
        <div className="text-zinc-100 tabular-nums text-right">
          {classMigrations}
        </div>
      </div>

      {/* QT status chips */}
      {latestClass && (
        <div className="text-zinc-500 mb-1">{latestClass} kg class</div>
      )}
      <div className="flex flex-wrap gap-1">
        {QT_CHIPS.map((chip) => {
          const hit = chipHit(chip)
          return (
            <span
              key={chip.label}
              className={
                'inline-block px-1.5 py-0.5 rounded text-xs ' +
                (hit === true
                  ? 'bg-emerald-900 text-emerald-300 border border-emerald-700'
                  : hit === false
                    ? 'bg-zinc-800 text-zinc-500 border border-zinc-700'
                    : 'bg-zinc-900 text-zinc-600 border border-zinc-800')
              }
            >
              {hit === true ? '✓' : hit === false ? '✗' : '?'} {chip.label}
            </span>
          )
        })}
      </div>
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
  isActive,
  xRange: xRangeProp,
  setXRange: setXRangeProp,
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
  isActive: boolean
  // URL-backed by LifterLookup for share-link round-trip. Optional so
  // CompareView can still be mounted standalone.
  xRange?: XRange
  setXRange?: (r: XRange) => void
}) {
  const [xRangeLocal, setXRangeLocal] = useState<XRange>('all')
  const xRange = xRangeProp ?? xRangeLocal
  const setXRange = setXRangeProp ?? setXRangeLocal
  // 'off' means no reference lines; otherwise it's the selected weight class.
  const [qtClass, setQtClass] = useState<string>('off')

  const historyQueries = useQueries({
    queries: compareNames.map((name) => ({
      queryKey: ['lifter-history', name],
      queryFn: () => fetchLifterHistory(name),
      enabled: !!name,
    })),
  })

  const { data: qtStandards } = useQuery({
    queryKey: ['qt-standards'],
    queryFn: fetchQtStandards,
    staleTime: 10 * 60 * 1000,
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
  const maxMonth = allMonths.reduce((a, b) => (a > b ? a : b), 0)

  // Collect QT values for the selected class so the y-axis can include them.
  const selectedQtRows = useMemo(() => {
    if (qtClass === 'off' || !qtStandards) return []
    // The selector value is "sex:class", e.g. "M:83".
    const [sex, wc] = qtClass.split(':')
    return qtStandards.filter(
      (r) => r.Sex === sex && r.WeightClass === wc,
    )
  }, [qtClass, qtStandards])

  const qtValues = selectedQtRows
    .flatMap((r) => [r.QT_2025, r.QT_2027])
    .filter((v): v is number => v != null)

  const allTotalsForAxis = [...allTotals, ...qtValues]
  const minTotalForAxis = allTotalsForAxis.length > 0
    ? allTotalsForAxis.reduce((a, b) => (a < b ? a : b), Infinity)
    : 0
  const maxTotalForAxis = allTotalsForAxis.length > 0
    ? allTotalsForAxis.reduce((a, b) => (a > b ? a : b), -Infinity)
    : 100
  const yMin = hasData ? Math.floor((minTotalForAxis - 25) / 25) * 25 : 0
  const yMax = hasData ? Math.ceil((maxTotalForAxis + 25) / 25) * 25 : 100

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

  // Build the list of class options for the QT selector.
  // Each loaded lifter contributes their current class as "sex:class".
  const qtClassOptions = useMemo(() => {
    const seen = new Set<string>()
    const opts: Array<{ value: string; label: string }> = []
    compareNames.forEach((_, i) => {
      const data = queryData[i]
      if (data?.found && data.sex && data.latest_weight_class) {
        const key = `${data.sex}:${data.latest_weight_class}`
        if (!seen.has(key)) {
          seen.add(key)
          opts.push({
            value: key,
            label: `${data.sex} ${data.latest_weight_class} kg`,
          })
        }
      }
    })
    return opts
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compareNames.join(','), ...queryData])

  // If the previously selected class is no longer available (lifter removed),
  // reset to 'off'.
  const qtClassValid =
    qtClass === 'off' || qtClassOptions.some((o) => o.value === qtClass)
  const effectiveQtClass = qtClassValid ? qtClass : 'off'

  // QT reference lines for the selected class (four: Reg/Nat x 2025/2027).
  const qtReferenceLines = useMemo(() => {
    if (effectiveQtClass === 'off' || !qtStandards) return []
    const [sex, wc] = effectiveQtClass.split(':')
    const rows = qtStandards.filter(
      (r) => r.Sex === sex && r.WeightClass === wc,
    )
    const lines: Array<{ value: number; label: string; stroke: string }> = []
    for (const chip of QT_CHIPS) {
      const row = rows.find((r) => r.Level === chip.level)
      const val = row?.[chip.field]
      if (val != null) {
        lines.push({ value: val, label: `${chip.label} (${val.toFixed(0)})`, stroke: chip.stroke })
      }
    }
    return lines
  }, [effectiveQtClass, qtStandards])

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

      {/* Right pane: summary cards + chart */}
      <div className="lg:col-span-2">
        {/* Per-lifter summary cards */}
        {compareNames.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            {compareNames.map((name, i) => (
              <LifterCard
                key={name}
                name={name}
                color={COMPARE_COLORS[i % COMPARE_COLORS.length]}
                history={queryData[i]}
                standards={qtStandards}
              />
            ))}
          </div>
        )}

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

            {/* QT class selector */}
            {qtClassOptions.length > 0 && (
              <div className="flex items-center gap-2 mb-2 text-sm flex-wrap">
                <span className="text-zinc-400">Show QT for class:</span>
                <select
                  value={effectiveQtClass}
                  onChange={(e) => setQtClass(e.target.value)}
                  className="bg-zinc-800 border border-zinc-700 rounded px-2 py-0.5 text-xs text-zinc-200 focus:outline-none focus:border-zinc-500"
                >
                  <option value="off">off</option>
                  {qtClassOptions.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            )}

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

            <details className="mb-2 max-w-2xl">
              <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
                Methodology and caveats
              </summary>
              <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
                <p>
                  <span className="text-zinc-400 font-medium">X-axis anchoring:</span>{' '}
                  Each lifter's curve starts at month 0, defined as their own first
                  full-power (SBD) meet in the dataset. This means you are comparing
                  progression rates, not calendar dates. A lifter who debuted in 2018 and
                  a lifter who debuted in 2024 will overlap on the same x-axis if their
                  careers are the same length.
                </p>
                <p>
                  <span className="text-zinc-400 font-medium">Career length mismatch:</span>{' '}
                  Comparing a 10-year career against a 1-year career on a shared x-axis
                  compresses the shorter career near the origin and is visually
                  misleading. The x-axis range selector above (6mo / 1y / 2y / 5y / All)
                  lets you zoom to a common window. An amber hint appears when career
                  lengths differ by 4x or more.
                </p>
                <p>
                  <span className="text-zinc-400 font-medium">Tooltip resolution:</span>{' '}
                  Hover values show each lifter's closest actual meet within +/- 3 months
                  of the hover position. Lifters without a meet near that position drop
                  out of the tooltip rather than showing an interpolated value. Nothing
                  between two meets is made up.
                </p>
                <p>
                  <span className="text-zinc-400 font-medium">QT reference lines:</span>{' '}
                  The optional QT lines use a single weight class picked from the
                  dropdown above. Lifters in the comparison who compete in a different
                  class will read those lines as informational only, not as their own
                  qualifying threshold.
                </p>
                <p>
                  <span className="text-zinc-400 font-medium">Summary cards:</span>{' '}
                  Best total, rate kg/month, meet count, first-meet date, class migration
                  count, and QT status above the chart are computed per lifter across
                  their full SBD history in the dataset, not restricted to the x-axis
                  range. They reflect the lifter's actual shape, not the chart window.
                </p>
                <p>
                  <a
                    href="?tab=about"
                    className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
                  >
                    See the About tab for full methodology, references, and disclaimers.
                  </a>
                </p>
              </div>
            </details>

            <div className="h-80 md:h-[480px] bg-zinc-900 rounded border border-zinc-800 p-2">
              {isActive && (
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
                  {/* QT reference lines for selected class */}
                  {qtReferenceLines.map((rl) => (
                    <ReferenceLine
                      key={rl.label}
                      y={rl.value}
                      stroke={rl.stroke}
                      strokeDasharray="4 4"
                      label={{
                        value: rl.label,
                        position: 'insideTopRight',
                        fill: rl.stroke,
                        fontSize: 10,
                        offset: 4,
                      }}
                    />
                  ))}
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
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
