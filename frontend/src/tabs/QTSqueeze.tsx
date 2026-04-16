// QT Squeeze tab (M5).
//
// Four-block Open-only view of CPU qualifying total coverage:
//   F Regionals, F Nationals, M Regionals, M Nationals
// Each block: 8 weight classes x 3 percentage columns (Pre-2025, 2025, 2027 Today).
//
// Numbers come from /api/qt/blocks which uses Division='Open' as the Open
// filter. The old qt_coverage_results.csv mixed all age classes and is
// superseded — the explanatory copy at the top says so.

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

type BlockKey = keyof QtBlocksResponse

const BLOCK_ORDER: { key: BlockKey; title: string }[] = [
  { key: 'M_Nationals', title: 'Men · Open · Nationals' },
  { key: 'M_Regionals', title: 'Men · Open · Regionals' },
  { key: 'F_Nationals', title: 'Women · Open · Nationals' },
  { key: 'F_Regionals', title: 'Women · Open · Regionals' },
]

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

function Block({ title, rows }: { title: string; rows: QtBlockRow[] }) {
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
      <h3 className="text-zinc-100 font-semibold mb-3">{title}</h3>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Table */}
        <div className="lg:col-span-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-zinc-400 text-xs uppercase tracking-wide">
              <tr className="border-b border-zinc-800">
                <th className="text-left py-2 pr-4 font-normal">Weight class</th>
                <th className="text-right py-2 px-2 font-normal">Pre-2025</th>
                <th className="text-right py-2 px-2 font-normal">2025</th>
                <th className="text-right py-2 pl-2 font-normal">2027 Today</th>
              </tr>
            </thead>
            <tbody className="text-zinc-200">
              {rows.map((r) => (
                <tr key={r.WeightClass} className="border-b border-zinc-900">
                  <td className="py-2 pr-4 text-zinc-300">{r.WeightClass}</td>
                  <td className="py-2 px-2 text-right tabular-nums">{fmtPct(r.pct_pre2025)}</td>
                  <td className="py-2 px-2 text-right tabular-nums">{fmtPct(r.pct_2025)}</td>
                  <td className="py-2 pl-2 text-right tabular-nums">{fmtPct(r.pct_2027_today)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Chart */}
        <div className="lg:col-span-3 h-64 bg-zinc-900 rounded border border-zinc-800 p-2">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 12, bottom: 24, left: 0 }}>
              <CartesianGrid stroke="#3f3f46" strokeDasharray="3 3" />
              <XAxis
                dataKey="weight_class"
                stroke="#a1a1aa"
                label={{ value: 'Weight class (kg)', position: 'insideBottom', offset: -8, fill: '#a1a1aa' }}
              />
              <YAxis
                stroke="#a1a1aa"
                tickFormatter={(v: number) => v + '%'}
                domain={[0, 100]}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46', color: '#e4e4e7' }}
                formatter={(v) =>
                  typeof v === 'number' ? v.toFixed(2) + '%' : String(v ?? '—')
                }
              />
              <Legend />
              <Bar dataKey="pre2025" name="Pre-2025" fill={COLORS.pre2025} isAnimationActive={false} />
              <Bar dataKey="cur2025" name="2025" fill={COLORS.cur2025} isAnimationActive={false} />
              <Bar dataKey="cur2027" name="2027 Today" fill={COLORS.cur2027} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  )
}

// ---------- Tab component ----------

export default function QTSqueeze() {
  const blocksQuery = useQuery<QtBlocksResponse>({
    queryKey: ['qt-blocks'],
    queryFn: fetchQtBlocks,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const handleDownloadCsv = () => {
    if (!blocksQuery.data) return
    downloadText('qt_coverage_open.csv', buildFlatCsv(blocksQuery.data), 'text/csv')
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
      downloadText('qt_coverage_open_columns.txt', text)
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-zinc-100 text-lg font-semibold">QT Squeeze</h2>
        <p className="text-zinc-300 text-sm mt-1 max-w-3xl">
          Percentage of <span className="text-zinc-100 font-medium">Open</span> lifters in
          each weight class who meet the CPU qualifying total. Three columns per row:
          pre-2025, 2025, and the forward-looking fraction of today's Open lifters who
          already meet the 2027 standard.
        </p>
        <details className="mt-2 max-w-3xl">
          <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
            Note on denominator
          </summary>
          <p className="text-zinc-500 text-xs mt-1">
            Open here means Division='Open' in OpenIPF. Earlier versions of this analysis
            mixed Juniors and Masters into the denominator and produced inflated coverage.
            Those numbers are superseded by what you see here.
          </p>
        </details>
      </div>

      <div className="flex gap-2 mb-6">
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

      {blocksQuery.isLoading && (
        <div className="text-zinc-500 text-sm">
          Loading…
          <div className="text-zinc-600 text-xs mt-1">
            First visit after a while can take up to ~50 s while the server wakes up.
          </div>
        </div>
      )}
      {blocksQuery.error && (
        <div className="text-red-400 text-sm">
          Load failed: {(blocksQuery.error as Error).message}
        </div>
      )}

      {blocksQuery.data &&
        BLOCK_ORDER.map(({ key, title }) => (
          <Block key={key} title={title} rows={blocksQuery.data![key]} />
        ))}
    </div>
  )
}
