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

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
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

  const qts = findQtForLifter(standards, history.sex, history.latest_weight_class)
  const qtField = ERA_QT_FIELD[era]
  const regionalsQt = qts.regionals?.[qtField]
  const nationalsQt = qts.nationals?.[qtField]

  const chartData = useMemo(
    () =>
      history.meets.map((m: LifterMeet) => ({
        date: m.Date,
        days: m.DaysFromFirst,
        total: m.TotalKg,
        meet: m.MeetName ?? '',
        division: m.Division ?? '',
        weight_class: m.CanonicalWeightClass ?? '',
      })),
    [history.meets],
  )

  // Y axis padding so reference lines don't sit on the edge.
  const allTotals = chartData.map((d) => d.total)
  if (regionalsQt) allTotals.push(regionalsQt)
  if (nationalsQt) allTotals.push(nationalsQt)
  const yMin = Math.floor((Math.min(...allTotals) - 25) / 25) * 25
  const yMax = Math.ceil((Math.max(...allTotals) + 25) / 25) * 25

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
          <div className="text-zinc-500 text-xs">{history.meet_count} meets</div>
        </div>
      </div>

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

      <div className="h-[400px] bg-zinc-900 rounded border border-zinc-800 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 16, right: 24, bottom: 24, left: 8 }}>
            <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              stroke="#a1a1aa"
              label={{ value: 'Date', position: 'insideBottom', offset: -8, fill: '#a1a1aa' }}
            />
            <YAxis
              stroke="#a1a1aa"
              domain={[yMin, yMax]}
              label={{
                value: 'Total (kg)',
                angle: -90,
                position: 'insideLeft',
                fill: '#a1a1aa',
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
              labelFormatter={(label) => String(label ?? '')}
            />
            <Legend />
            {regionalsQt && (
              <ReferenceLine
                y={regionalsQt}
                stroke="#94a3b8"
                strokeDasharray="4 4"
                label={{ value: `Regionals ${ERA_LABEL[era]}`, position: 'right', fill: '#94a3b8', fontSize: 11 }}
              />
            )}
            {nationalsQt && (
              <ReferenceLine
                y={nationalsQt}
                stroke="#ce9178"
                strokeDasharray="4 4"
                label={{ value: `Nationals ${ERA_LABEL[era]}`, position: 'right', fill: '#ce9178', fontSize: 11 }}
              />
            )}
            <Line
              type="monotone"
              dataKey="total"
              name="Total"
              stroke="#569cd6"
              strokeWidth={2}
              dot={{ r: 4, fill: '#569cd6' }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Meet table */}
      <div className="mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-zinc-400 text-xs uppercase tracking-wide">
            <tr className="border-b border-zinc-800">
              <th className="text-left py-2 pr-4 font-normal">Date</th>
              <th className="text-left py-2 pr-4 font-normal">Meet</th>
              <th className="text-left py-2 pr-4 font-normal">Class</th>
              <th className="text-left py-2 pr-4 font-normal">Division</th>
              <th className="text-right py-2 pl-2 font-normal">S / B / D</th>
              <th className="text-right py-2 pl-2 font-normal">Total</th>
              <th className="text-right py-2 pl-2 font-normal">Δ first</th>
            </tr>
          </thead>
          <tbody className="text-zinc-200">
            {history.meets.map((m, i) => (
              <tr key={i} className="border-b border-zinc-900">
                <td className="py-2 pr-4 text-zinc-300 whitespace-nowrap">{fmtDate(m.Date)}</td>
                <td className="py-2 pr-4 text-zinc-300">{m.MeetName ?? '—'}</td>
                <td className="py-2 pr-4 text-zinc-400 whitespace-nowrap">
                  {m.CanonicalWeightClass ? `${m.CanonicalWeightClass} kg` : '—'}
                </td>
                <td className="py-2 pr-4 text-zinc-400">{m.Division ?? '—'}</td>
                <td className="py-2 pl-2 text-right tabular-nums text-zinc-400 whitespace-nowrap">
                  {fmtSbd(m.Best3SquatKg, m.Best3BenchKg, m.Best3DeadliftKg)}
                </td>
                <td className="py-2 pl-2 text-right tabular-nums">{m.TotalKg.toFixed(1)}</td>
                <td className="py-2 pl-2 text-right tabular-nums text-zinc-400">
                  {m.TotalDiffFromFirst >= 0 ? '+' : ''}
                  {m.TotalDiffFromFirst.toFixed(1)}
                </td>
              </tr>
            ))}
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

      <div className="overflow-x-auto">
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

// ---------- Tab component ----------

type Mode = 'search' | 'manual'

export default function LifterLookup() {
  const [mode, setMode] = useState<Mode>('search')
  const [query, setQuery] = useState('')
  const [selectedName, setSelectedName] = useState<string | null>(null)
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
      <div className="mb-4 flex items-baseline justify-between">
        <div>
          <h2 className="text-zinc-100 text-lg font-semibold">Lifter lookup</h2>
          <p className="text-zinc-500 text-sm">
            Search any Canadian lifter in the CPU/IPF dataset, or enter your meets manually
            to project a trajectory.
          </p>
        </div>
        <div className="flex gap-1">
          {(['search', 'manual'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={
                'px-3 py-1.5 rounded text-sm ' +
                (mode === m
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
              }
            >
              {m === 'search' ? 'Search' : 'Manual entry'}
            </button>
          ))}
        </div>
      </div>

      {mode === 'search' ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left pane: search */}
          <div className="lg:col-span-1">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a name"
              className="w-full px-4 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
              autoFocus
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
            {selectedName && historyQuery.isLoading && (
              <div className="text-zinc-500 text-sm">Loading history…</div>
            )}
            {historyQuery.error && (
              <div className="text-red-400 text-sm">
                Error: {(historyQuery.error as Error).message}
              </div>
            )}
            {historyQuery.data && historyQuery.data.found && (
              <LifterDetail history={historyQuery.data} standards={standardsQuery.data} />
            )}
            {historyQuery.data && !historyQuery.data.found && (
              <div className="text-zinc-500 text-sm">No history found for {selectedName}.</div>
            )}
          </div>
        </div>
      ) : (
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
