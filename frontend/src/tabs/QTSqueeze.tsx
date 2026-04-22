// QT Squeeze tab (M5).
//
// Four-block view of CPU qualifying total coverage:
//   F Regionals, F Nationals, M Regionals, M Nationals
// Each block: 8 weight classes x 3 percentage columns (Pre-2025, 2025, 2027 Today).
//
// Numbers come from /api/qt/blocks. Division defaults to Open. Non-Open
// divisions currently return Open values with a `using_open_fallback`
// flag; the UI shows a banner noting that age-specific QTs are coming
// from powerlifting.ca/qualifying-standards.

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchQtBlocks, type QtBlockRow, type QtBlocksResponse } from '../lib/api'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'

type BlockKey = Exclude<keyof QtBlocksResponse, 'meta'>

const BLOCK_ORDER: { key: BlockKey; title: string }[] = [
  { key: 'M_Nationals', title: 'Men · Nationals' },
  { key: 'M_Regionals', title: 'Men · Regionals' },
  { key: 'F_Nationals', title: 'Women · Nationals' },
  { key: 'F_Regionals', title: 'Women · Regionals' },
]

const DIVISIONS = [
  'Sub-Junior',
  'Junior',
  'Open',
  'Master 1',
  'Master 2',
  'Master 3',
  'Master 4',
] as const

const COLORS = {
  pre2025: '#94a3b8',  // slate
  cur2025: '#569cd6',  // blue
  cur2027: '#ce9178',  // orange
}

// ---------- Formatting helpers ----------

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toFixed(2) + '%'
}

// ---------- CSV / clipboard exports ----------

function buildFlatCsv(blocks: QtBlocksResponse): string {
  const lines: string[] = ['Sex,Level,WeightClass,pct_pre2025,pct_2025,pct_2027_today']
  for (const { key } of BLOCK_ORDER) {
    const [sex, level] = key.split('_') as [string, string]
    for (const r of blocks[key]) {
      lines.push(
        [sex, level, r.WeightClass, r.pct_pre2025 ?? '', r.pct_2025 ?? '', r.pct_2027_today ?? ''].join(','),
      )
    }
  }
  return lines.join('\n')
}

function buildColumnText(blocks: QtBlocksResponse): string {
  // Google-Sheets-friendly per-block, per-column vertical dump.
  const out: string[] = []
  for (const { key, title } of BLOCK_ORDER) {
    const rows = blocks[key]
    out.push(title.toUpperCase())
    out.push('')
    out.push('Weight Class:')
    for (const r of rows) out.push(r.WeightClass)
    out.push('')
    out.push('Pre-2025:')
    for (const r of rows) out.push(fmtPct(r.pct_pre2025))
    out.push('')
    out.push('2025:')
    for (const r of rows) out.push(fmtPct(r.pct_2025))
    out.push('')
    out.push('2027 Today:')
    for (const r of rows) out.push(fmtPct(r.pct_2027_today))
    out.push('')
    out.push('')
  }
  return out.join('\n').trimEnd() + '\n'
}

function downloadText(filename: string, body: string, mime = 'text/plain') {
  const blob = new Blob([body], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ---------- Block sub-component ----------

function Block({ title, rows, isActive }: { title: string; rows: QtBlockRow[]; isActive: boolean }) {
  // Recharts wants flat objects with the value keys.
  const chartData = useMemo(
    () =>
      rows.map((r) => ({
        weight_class: r.WeightClass,
        pre2025: r.pct_pre2025 ?? 0,
        cur2025: r.pct_2025 ?? 0,
        cur2027: r.pct_2027_today ?? 0,
      })),
    [rows],
  )

  return (
    <section className="mb-10">
      <h3 className="text-zinc-100 font-semibold mt-4 mb-3">{title}</h3>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Table */}
        <div className="lg:col-span-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-zinc-400 text-xs uppercase tracking-wide">
              <tr className="border-b border-zinc-800">
                <th className="text-left py-2 pr-4 font-normal">Weight class</th>
                <th className="text-right py-2 px-2 font-normal hidden sm:table-cell">Pre-2025</th>
                <th className="text-right py-2 px-2 font-normal">2025</th>
                <th className="text-right py-2 pl-2 font-normal">2027</th>
              </tr>
            </thead>
            <tbody className="text-zinc-200">
              {rows.map((r) => (
                <tr key={r.WeightClass} className="border-b border-zinc-900">
                  <td className="py-2 pr-4 text-zinc-300">{r.WeightClass}</td>
                  <td className="py-2 px-2 text-right tabular-nums hidden sm:table-cell">{fmtPct(r.pct_pre2025)}</td>
                  <td className="py-2 px-2 text-right tabular-nums">{fmtPct(r.pct_2025)}</td>
                  <td className="py-2 pl-2 text-right tabular-nums">{fmtPct(r.pct_2027_today)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Chart */}
        <div className="lg:col-span-3 h-72 bg-zinc-900 rounded border border-zinc-800 p-2">
          {isActive && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
              <XAxis
                dataKey="weight_class"
                stroke="#a1a1aa"
                angle={-45}
                textAnchor="end"
                interval={0}
                height={56}
                tick={{ fontSize: 11, fill: '#a1a1aa' }}
                tickMargin={6}
              />
              <YAxis
                stroke="#a1a1aa"
                tickFormatter={(v: number) => v + '%'}
                domain={[0, 100]}
                tick={{ fontSize: 11 }}
                width={42}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46', color: '#e4e4e7' }}
                formatter={(v) =>
                  typeof v === 'number' ? v.toFixed(2) + '%' : String(v ?? '—')
                }
              />
              <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
              <Bar dataKey="pre2025" name="Pre-2025" fill={COLORS.pre2025} isAnimationActive={false} />
              <Bar dataKey="cur2025" name="2025" fill={COLORS.cur2025} isAnimationActive={false} />
              <Bar dataKey="cur2027" name="2027 Today" fill={COLORS.cur2027} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
          )}
        </div>
      </div>
    </section>
  )
}

// ---------- Tab component ----------

export default function QTSqueeze({ isActive }: { isActive: boolean }) {
  const [division, setDivision] = useState<string>('Open')

  const blocksQuery = useQuery<QtBlocksResponse>({
    queryKey: ['qt-blocks', division],
    queryFn: () => fetchQtBlocks(division),
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const handleDownloadCsv = () => {
    if (!blocksQuery.data) return
    const suffix = division.toLowerCase().replace(/\s+/g, '_')
    downloadText(`qt_coverage_${suffix}.csv`, buildFlatCsv(blocksQuery.data), 'text/csv')
  }

  const [copyLabel, setCopyLabel] = useState('Copy for Sheets')

  const handleCopyColumns = async () => {
    if (!blocksQuery.data) return
    const text = buildColumnText(blocksQuery.data)
    try {
      await navigator.clipboard.writeText(text)
      setCopyLabel('Copied!')
      setTimeout(() => setCopyLabel('Copy for Sheets'), 2000)
    } catch {
      // Fallback for older browsers — dump to a download.
      downloadText('qt_coverage_columns.txt', text)
    }
  }

  const usingFallback =
    blocksQuery.data?.meta?.using_open_fallback === true && division !== 'Open'

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-zinc-100 text-lg font-semibold">QT Squeeze</h2>
        <p className="text-zinc-300 text-sm mt-1 max-w-3xl">
          Percentage of lifters in each weight class who meet the CPU qualifying
          total. Three columns per row: pre-2025, 2025, and the forward-looking
          fraction of today's lifters who already meet the 2027 standard.
        </p>
        <details className="mt-2 max-w-3xl">
          <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
            Methodology and caveats
          </summary>
          <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
            <p>
              <span className="text-zinc-400 font-medium">Open denominator:</span> Open
              here means Division='Open' in OpenIPF. Earlier versions of this analysis
              mixed Juniors and Masters into the denominator and produced inflated
              coverage numbers. Those older numbers are superseded by what you see here.
              Use the Age division dropdown to see coverage for non-Open divisions.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">24-month windows:</span> For
              the 2025 and 2027 columns, "In 24m to Nats" counts meets where the lifter
              hit the qualifying total within the 24-month window that ends on March 1
              of the standard's year (the CPU Nationals qualifying cutoff). A lifter who
              hit the 2027 QT in March 2024 is in the 2027 window. A lifter who hit it
              in February 2025 is NOT, because February 2025 is outside a window ending
              March 2027 minus 24 months.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">Per-lifter, not per-meet:</span>{' '}
              Coverage is computed on the lifter's best qualifying total inside the
              window, not on individual meet results. One lifter who hits the standard
              three times in a window counts once in the numerator. A lifter who has
              never hit the standard counts once in the denominator and zero in the
              numerator.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">Age division data:</span>{' '}
              Non-Open divisions (Sub-Junior, Junior, Master 1-4) currently display using
              the Open qualifying totals as a placeholder until the per-division CSV
              from powerlifting.ca is transcribed into the dataset. An amber banner
              appears at the top of the table when a non-Open division is selected.
              Treat those numbers as directionally correct but not authoritative against
              the published per-division standards.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">Scope:</span> Canadian lifters
              in IPF-sanctioned meets only. Non-IPF federations (CPF, WPC, GPC) are
              excluded at the parquet level. This site is not affiliated with the CPU
              or IPF.
            </p>
          </div>
        </details>
      </div>

      <div className="flex flex-wrap items-end gap-3 mb-4">
        <label className="flex flex-col text-xs text-zinc-400">
          <span className="mb-1">Age division</span>
          <select
            value={division}
            onChange={(e) => setDivision(e.target.value)}
            className="px-2 py-1.5 bg-zinc-800 text-zinc-100 text-sm rounded border border-zinc-700 min-w-[140px]"
            aria-label="Age division"
          >
            {DIVISIONS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </label>
        <button
          onClick={handleDownloadCsv}
          disabled={!blocksQuery.data}
          className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-100 text-sm rounded border border-zinc-700"
        >
          Download CSV
        </button>
        <button
          onClick={handleCopyColumns}
          disabled={!blocksQuery.data}
          className="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-100 text-sm rounded border border-zinc-700"
        >
          {copyLabel}
        </button>
      </div>

      {usingFallback && (
        <div
          role="note"
          className="mb-5 px-3 py-2 rounded border border-amber-700/60 bg-amber-950/40 text-amber-200 text-sm max-w-3xl"
        >
          <span className="font-medium">Open values shown.</span> Age-specific
          QTs for <span className="font-medium">{division}</span> are coming
          from powerlifting.ca/qualifying-standards.
        </div>
      )}

      {blocksQuery.isLoading && <LoadingSkeleton lines={4} chart />}
      {blocksQuery.isError && (
        <QueryErrorCard
          error={blocksQuery.error}
          onRetry={() => blocksQuery.refetch()}
          label="QT coverage"
        />
      )}

      {blocksQuery.data &&
        BLOCK_ORDER.map(({ key, title }) => (
          <Block key={key} title={title} rows={blocksQuery.data![key]} isActive={isActive} />
        ))}
    </div>
  )
}
