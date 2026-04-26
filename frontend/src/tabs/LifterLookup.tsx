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
import { ShareButton } from '../lib/ShareButton'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
import {
  fetchLifterHistory,
  fetchLifterSearch,
  fetchQtStandards,
  postManualTrajectory,
  type LifterHistory,
  type LifterSearchResult,
  type ManualEntry,
  type QtStandardRow,
} from '../lib/api'

// LifterDetail is lazy-loaded so Recharts (~200 KB) only ships to clients
// who actually open a lifter detail view or use manual entry. Matches the
// existing CompareView split convention — do NOT statically import anything
// from LifterDetail.tsx back into this file; that would re-merge the lazy
// chunk into the main bundle and Vite would warn INEFFECTIVE_DYNAMIC_IMPORT.
const LifterDetail = lazy(() => import('./LifterDetail'))

// ---------- Debounce hook ----------

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

// ---------- Manual entry form ----------

type ManualFormRow = {
  date: string
  total: string
  squat: string
  bench: string
  deadlift: string
  weight_class: string
  meet_name: string
}

const EMPTY_ROW: ManualFormRow = {
  date: '',
  total: '',
  squat: '',
  bench: '',
  deadlift: '',
  weight_class: '',
  meet_name: '',
}

// A row is ready to submit when it has a date plus either a valid total or
// all three lift values. Any other combination is flagged client-side so the
// user sees the issue before hitting the server.
function rowReady(r: ManualFormRow): boolean {
  if (!r.date) return false
  const hasTotal = r.total !== '' && Number(r.total) > 0
  const hasSquat = r.squat !== '' && Number(r.squat) > 0
  const hasBench = r.bench !== '' && Number(r.bench) > 0
  const hasDead = r.deadlift !== '' && Number(r.deadlift) > 0
  const hasAllLifts = hasSquat && hasBench && hasDead
  return hasTotal || hasAllLifts
}

function rowHasPartialLifts(r: ManualFormRow): boolean {
  const hasSquat = r.squat !== '' && Number(r.squat) > 0
  const hasBench = r.bench !== '' && Number(r.bench) > 0
  const hasDead = r.deadlift !== '' && Number(r.deadlift) > 0
  const count = Number(hasSquat) + Number(hasBench) + Number(hasDead)
  return count > 0 && count < 3
}

function ManualEntryForm({
  onSubmit,
  pending,
  result,
  error,
  standards,
  isActive,
}: {
  onSubmit: (req: { sex: string; rows: ManualFormRow[] }) => void
  pending: boolean
  result: LifterHistory | null
  error: Error | null
  standards: QtStandardRow[] | undefined
  isActive: boolean
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

  const validRows = rows.filter(rowReady)
  const canSubmit = validRows.length >= 1
  const hasPartialLiftWarning = rows.some(rowHasPartialLifts)

  return (
    <div>
      <h3 className="text-zinc-100 text-lg font-semibold mb-1">Manual entry</h3>
      <p className="text-zinc-500 text-sm mb-2">
        Enter your meets below if you're not in the OpenIPF dataset, or to project a
        hypothetical trajectory.
      </p>
      <p className="text-zinc-500 text-xs mb-2">
        Enter a total on its own, or fill all three lifts (squat, bench, deadlift)
        to populate the per-lift chart. If you enter both, they must match.
      </p>

      <details className="mb-4 max-w-2xl">
        <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
          Methodology and caveats
        </summary>
        <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
          <p>
            <span className="text-zinc-400 font-medium">Personal-only projection:</span>{' '}
            The trajectory and projection shown below come solely from the meets you
            enter in this form. They do NOT blend in any cohort average. If you enter
            fewer than 5 meets, the projection will be very noisy and should not be
            trusted as a forecast.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">Linear fit only:</span> The
            extrapolation line is ordinary linear regression through your SBD meets.
            Breakthroughs, plateaus, injuries, and comeback arcs all flatten into a
            single slope. Use the output as a rough baseline, not a prediction.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">Not persisted:</span> Manually
            entered meets stay in your browser session only. Nothing is saved server
            side, nothing is shared with other users, nothing is merged into the
            OpenPowerlifting dataset. Close the tab and the entries are gone.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">QT reference lines:</span>{' '}
            The dashed horizontal lines on the chart use CPU qualifying totals for the
            weight class of your most recent entry. Switching your entered weight class
            across meets will redraw them against the latest one.
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
              <th className="text-left py-2 pr-2 font-normal">Squat</th>
              <th className="text-left py-2 pr-2 font-normal">Bench</th>
              <th className="text-left py-2 pr-2 font-normal">Deadlift</th>
              <th className="text-left py-2 pr-2 font-normal">Total</th>
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
                    value={r.squat}
                    onChange={(e) => updateRow(i, { squat: e.target.value })}
                    placeholder="kg"
                    aria-label="Squat (kg)"
                    className="w-20 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={r.bench}
                    onChange={(e) => updateRow(i, { bench: e.target.value })}
                    placeholder="kg"
                    aria-label="Bench (kg)"
                    className="w-20 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={r.deadlift}
                    onChange={(e) => updateRow(i, { deadlift: e.target.value })}
                    placeholder="kg"
                    aria-label="Deadlift (kg)"
                    className="w-20 px-2 py-1 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="0.5"
                    min="0"
                    value={r.total}
                    onChange={(e) => updateRow(i, { total: e.target.value })}
                    placeholder="auto"
                    aria-label="Total (kg)"
                    title="Leave blank to auto-sum from squat, bench, and deadlift"
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
                  placeholder="auto from S/B/D"
                  inputMode="decimal"
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                />
              </label>
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Squat (kg)
                </span>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={r.squat}
                  onChange={(e) => updateRow(i, { squat: e.target.value })}
                  placeholder="optional"
                  inputMode="decimal"
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                />
              </label>
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Bench (kg)
                </span>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={r.bench}
                  onChange={(e) => updateRow(i, { bench: e.target.value })}
                  placeholder="optional"
                  inputMode="decimal"
                  className="w-full px-2 py-1.5 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 text-sm tabular-nums"
                />
              </label>
              <label className="block">
                <span className="text-zinc-400 text-xs uppercase tracking-wide block mb-1">
                  Deadlift (kg)
                </span>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  value={r.deadlift}
                  onChange={(e) => updateRow(i, { deadlift: e.target.value })}
                  placeholder="optional"
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
              <label className="block col-span-2">
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
          disabled={!canSubmit || pending || hasPartialLiftWarning}
          className="px-3 py-1.5 bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 text-zinc-100 text-sm rounded border border-zinc-600"
        >
          {pending ? 'Computing…' : 'Compute trajectory'}
        </button>
      </div>

      {hasPartialLiftWarning && (
        <div className="mt-3 text-orange-400 text-sm">
          Some rows have one or two lifts filled but not all three. Fill in squat,
          bench, and deadlift together, or clear them to enter a total only.
        </div>
      )}

      {error && (
        <div className="mt-3 text-red-400 text-sm">Error: {error.message}</div>
      )}

      {result && (
        <div className="mt-6">
          <Suspense fallback={<LoadingSkeleton lines={3} chart />}>
            <LifterDetail history={result} standards={standards} isActive={isActive} />
          </Suspense>
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
// Detail-view state shared via URL so single-lifter deep links round-trip
// cleanly. These mirror the state shape LifterDetail / CompareView used
// to hold internally; moved up to LifterLookup so useUrlState can back them.
export type LookupEra = 'pre2025' | '2025' | '2027'
export type LookupViewMode = 'total' | 'per_lift'
export type LookupRange = 'all' | '6' | '12' | '24' | '60'


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

export default function LifterLookup({ isActive }: { isActive: boolean }) {
  // URL state covers all shareable lookup views:
  //   ?tab=lookup                                  -> search, nothing selected
  //   ?tab=lookup&lifter=Matthias%20Bernhard       -> deep-link to a lifter
  //   ?tab=lookup&mode=compare&lifters=A,B,C       -> multi-lifter comparison
  //   ?tab=lookup&mode=manual                      -> manual trajectory form
  const [urlState, setUrlState] = useUrlState({
    mode: 'search',
    lifter: '',
    lifters: '',
    // Detail-view state (search mode). Defaults match the prior useState
    // defaults on LifterDetail so existing bookmarks keep rendering the
    // same thing they did before this refactor.
    era: '2025',
    view_mode: 'total',
    // Compare-view x-axis range.
    range: 'all',
  })
  const mode: Mode = parseMode(urlState.mode)
  const selectedName: string | null = urlState.lifter ? urlState.lifter : null
  const compareNames: string[] = useMemo(
    () => parseLifters(urlState.lifters),
    [urlState.lifters],
  )
  const era: LookupEra =
    urlState.era === 'pre2025' || urlState.era === '2025' || urlState.era === '2027'
      ? (urlState.era as LookupEra)
      : '2025'
  const viewMode: LookupViewMode =
    urlState.view_mode === 'per_lift' ? 'per_lift' : 'total'
  const xRange: LookupRange =
    urlState.range === '6' ||
    urlState.range === '12' ||
    urlState.range === '24' ||
    urlState.range === '60'
      ? (urlState.range as LookupRange)
      : 'all'

  const setMode = (m: Mode) => {
    setUrlState({ mode: m })
    setQuery('')  // clear stale search text when switching modes
  }
  const setSelectedName = (name: string | null) =>
    setUrlState({ lifter: name ?? '' })
  const setCompareNames = (names: string[]) =>
    setUrlState({ lifters: names.slice(0, MAX_COMPARE).join(',') })
  const setEra = (e: LookupEra) => setUrlState({ era: e })
  const setViewMode = (v: LookupViewMode) => setUrlState({ view_mode: v })
  const setXRange = (r: LookupRange) => setUrlState({ range: r })
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
      const entries: ManualEntry[] = rows.map((r) => {
        const entry: ManualEntry = {
          date: r.date,
          weight_class: r.weight_class || null,
          meet_name: r.meet_name || null,
        }
        if (r.total !== '' && Number(r.total) > 0) entry.total_kg = Number(r.total)
        if (r.squat !== '' && Number(r.squat) > 0) entry.squat_kg = Number(r.squat)
        if (r.bench !== '' && Number(r.bench) > 0) entry.bench_kg = Number(r.bench)
        if (r.deadlift !== '' && Number(r.deadlift) > 0) entry.deadlift_kg = Number(r.deadlift)
        return entry
      })
      return postManualTrajectory({ name: '(manual entry)', sex, entries })
    },
  })

  return (
    <div>
      <div className="mb-4 flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-3">
        <div className="max-w-2xl">
          <h2 className="text-zinc-100 text-lg font-semibold">Lifter lookup</h2>
          <p className="text-zinc-500 text-sm">
            Search any Canadian lifter in the CPU/IPF dataset, or enter your meets manually
            to project a trajectory. Lifters who share the same name in the OpenPowerlifting
            database may show merged histories.
          </p>
          <details className="mt-2">
            <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
              Methodology and caveats
            </summary>
            <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
              <p>
                <span className="text-zinc-400 font-medium">Scope:</span> All trends,
                projections, and percentile ranks on this page are computed against Canadian
                IPF-affiliated meet data only. Meets a lifter has competed in outside Canada
                or outside IPF-sanctioned federations are NOT reflected. If a lifter looks
                weaker here than you expect, check whether most of their meets were
                non-IPF.
              </p>
              <p>
                <span className="text-zinc-400 font-medium">QT reference lines:</span> The
                dashed horizontal lines on the trajectory chart are CPU qualifying totals
                specifically (Regionals and Nationals, 2025 and 2027 standards). Other
                federations use different standards. The line set shown depends on the
                lifter's most recent weight class.
              </p>
              <p>
                <span className="text-zinc-400 font-medium">Name collisions:</span> Lifters
                sharing the same name in OpenPowerlifting may appear as a single merged
                history. The dataset has no unique person identifier, so disambiguation is
                not possible here. If results look off, cross-reference meet locations and
                dates against your own records.
              </p>
              <p>
                <span className="text-zinc-400 font-medium">Projection math:</span> The
                dashed extrapolation line is ordinary linear regression through the
                lifter's SBD meets. It does NOT blend in the cohort average. Lifters with
                plateaus, breakthroughs, injury breaks, or comeback arcs will see an
                oversimplified straight line. Treat the projection as a baseline, not a
                forecast.
              </p>
              <p>
                <span className="text-zinc-400 font-medium">Partial-lift meets:</span> The
                trajectory chart filters to full-power (SBD) meets so the y-axis is a
                single comparable total. Bench-only and push-pull meets still appear in
                the meet table below the chart, muted, with the event type chip and a
                delta column computed against the first SBD meet.
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
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div
            className="flex gap-2 -mx-1 px-1 overflow-x-auto"
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
          {/* Share is only meaningful when there's something specific in the
              URL beyond tab+mode: a selected lifter (search) or a populated
              compare list. Hide it on the bare search landing + manual form. */}
          {((mode === 'search' && selectedName) ||
            (mode === 'compare' && compareNames.length > 0)) && (
            <ShareButton ariaLabel="Copy shareable link to this lookup" />
          )}
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
              <Suspense fallback={<LoadingSkeleton lines={3} chart />}>
                <LifterDetail
                  history={historyQuery.data}
                  standards={standardsQuery.data}
                  isActive={isActive}
                  era={era}
                  setEra={setEra}
                  viewMode={viewMode}
                  setViewMode={setViewMode}
                />
              </Suspense>
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
            isActive={isActive}
            xRange={xRange}
            setXRange={setXRange}
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
          isActive={isActive}
        />
      )}
    </div>
  )
}
