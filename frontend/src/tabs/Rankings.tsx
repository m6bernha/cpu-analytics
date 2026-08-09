// Rankings tab — Phase 0 of the stateless social layer.
// See docs/adr/0002-social-layer-stateless.md.
//
// Leaderboard of lifters active in the last 24 months, Raw SBD only
// (IPF GL coefficients are Raw-Classic-specific). Ranked by GLP or raw
// total, with a percentile standing badge per row.

import { useQuery } from '@tanstack/react-query'

import {
  fetchFilters,
  fetchPercentileCurves,
  fetchRankings,
  type RankingsResponse,
} from '../lib/api'
import { PercentileBadge } from '../components/PercentileBadge'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
import { ShareButton } from '../lib/ShareButton'
import { fmtKg } from '../lib/format'
import { athletePath, navigate } from '../lib/route'
import { useUrlState } from '../lib/useUrlState'

interface RankingsProps {
  isActive: boolean
}

const PAGE_SIZE = 50

const METRICS: { key: string; label: string }[] = [
  { key: 'glp', label: 'IPF GL Points' },
  { key: 'total', label: 'Total' },
]

export default function Rankings({ isActive }: RankingsProps) {
  const [url, setUrl] = useUrlState({
    rk_sex: 'All',
    rk_class: 'All',
    rk_div: 'All',
    rk_metric: 'glp',
    rk_page: '0',
  })
  const page = Math.max(0, parseInt(url.rk_page, 10) || 0)

  const filtersQ = useQuery({
    queryKey: ['filters'],
    queryFn: fetchFilters,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const curvesQ = useQuery({
    queryKey: ['rankings', 'percentiles'],
    queryFn: fetchPercentileCurves,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const rankingsQ = useQuery<RankingsResponse>({
    queryKey: ['rankings', url.rk_sex, url.rk_class, url.rk_div, url.rk_metric, page],
    queryFn: () =>
      fetchRankings({
        sex: url.rk_sex,
        weight_class: url.rk_class,
        division: url.rk_div,
        metric: url.rk_metric,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const data = rankingsQ.data
  // Class list depends on the selected sex; "All" shows the union so a
  // user can still narrow without picking a sex first.
  const classes = (() => {
    const wc = filtersQ.data?.weight_class
    if (!wc) return []
    if (url.rk_sex === 'M') return wc.M
    if (url.rk_sex === 'F') return wc.F
    return [...wc.M, ...wc.F]
  })()

  const set = (patch: Record<string, string>) =>
    setUrl({ ...patch, rk_page: '0' })

  const nPages = data ? Math.ceil(data.n_total / PAGE_SIZE) : 0

  return (
    <div className={isActive ? 'space-y-4' : 'space-y-4 hidden'}>
      <div>
        <div className="flex items-center gap-3 flex-wrap">
          <h2 className="text-zinc-100 text-base font-semibold">Rankings</h2>
          <ShareButton surface="rankings" />
        </div>
        <p className="text-zinc-400 text-xs mt-1 max-w-2xl">
          Canadian lifters at IPF-sanctioned meets who competed in the last
          24 months, ranked by their best result in that window. Raw full
          power only.
          {data?.window_start && data?.window_end && (
            <> Window: {data.window_start} to {data.window_end}.</>
          )}
        </p>
      </div>

      <div className="flex flex-wrap gap-3 items-end">
        <label className="text-xs text-zinc-400 space-y-1">
          <span className="block">Sex</span>
          <select
            value={url.rk_sex}
            onChange={(e) => set({ rk_sex: e.target.value, rk_class: 'All' })}
            className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus-visible:border-zinc-500"
          >
            <option value="All">All</option>
            <option value="F">Women</option>
            <option value="M">Men</option>
          </select>
        </label>

        <label className="text-xs text-zinc-400 space-y-1">
          <span className="block">Weight class</span>
          <select
            value={url.rk_class}
            onChange={(e) => set({ rk_class: e.target.value })}
            className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus-visible:border-zinc-500"
          >
            <option value="All">All</option>
            {classes.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </label>

        <label className="text-xs text-zinc-400 space-y-1">
          <span className="block">Division</span>
          <select
            value={url.rk_div}
            onChange={(e) => set({ rk_div: e.target.value })}
            className="bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus-visible:border-zinc-500"
          >
            {(filtersQ.data?.division ?? ['All']).map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </label>

        <div className="text-xs text-zinc-400 space-y-1">
          <span className="block">Rank by</span>
          <div className="flex gap-1">
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => set({ rk_metric: m.key })}
                aria-pressed={url.rk_metric === m.key}
                className={
                  'px-3 py-1.5 rounded text-sm transition-colors ' +
                  (url.rk_metric === m.key
                    ? 'bg-zinc-800 text-zinc-100'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
                }
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {rankingsQ.isError && (
        <QueryErrorCard
          error={rankingsQ.error}
          onRetry={() => rankingsQ.refetch()}
          label="Rankings"
        />
      )}
      {rankingsQ.isLoading && <LoadingSkeleton lines={6} />}

      {data && data.rows.length === 0 && !rankingsQ.isLoading && (
        <p className="text-zinc-400 text-sm">
          No active lifters match these filters. Try widening the weight
          class or division.
        </p>
      )}

      {data && data.rows.length > 0 && (
        <>
          <div className="overflow-x-auto">
            <table className="text-sm min-w-full">
              <thead className="text-zinc-400 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="text-right pr-3 pb-1.5">#</th>
                  <th className="text-left pr-3 pb-1.5">Lifter</th>
                  <th className="text-left pr-3 pb-1.5">Standing</th>
                  <th className="text-left pr-3 pb-1.5 hidden sm:table-cell">Class</th>
                  <th className="text-left pr-3 pb-1.5 hidden md:table-cell">Div</th>
                  <th className="text-right pr-3 pb-1.5">Total</th>
                  <th className="text-right pr-3 pb-1.5 hidden sm:table-cell">GLP</th>
                  <th className="text-left pr-3 pb-1.5 hidden md:table-cell">Best meet</th>
                </tr>
              </thead>
              <tbody className="text-zinc-200">
                {data.rows.map((r) => (
                  <tr key={r.name} className="border-t border-zinc-900">
                    <td className="pr-3 py-1.5 text-right tabular-nums text-zinc-400">
                      {r.rank}
                    </td>
                    <td className="pr-3 py-1.5">
                      <a
                        href={athletePath(r.name)}
                        onClick={(e) => {
                          // Plain left-click routes in-app; modified clicks
                          // keep the browser's open-in-new-tab behaviour.
                          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
                          e.preventDefault()
                          navigate(athletePath(r.name))
                        }}
                        className="hover:text-orange-300 underline underline-offset-2 decoration-zinc-700"
                      >
                        {r.name}
                      </a>
                    </td>
                    <td className="pr-3 py-1.5">
                      <PercentileBadge
                        glp={r.glp}
                        sex={r.sex}
                        curves={curvesQ.data}
                      />
                    </td>
                    <td className="pr-3 py-1.5 text-zinc-400 hidden sm:table-cell">
                      {r.weight_class ?? '—'}
                    </td>
                    <td className="pr-3 py-1.5 text-zinc-400 hidden md:table-cell">
                      {r.division ?? '—'}
                    </td>
                    <td className="pr-3 py-1.5 text-right tabular-nums">
                      {fmtKg(r.total_kg, 1)}
                    </td>
                    <td className="pr-3 py-1.5 text-right tabular-nums text-zinc-300 hidden sm:table-cell">
                      {r.glp?.toFixed(1) ?? '—'}
                    </td>
                    <td className="pr-3 py-1.5 text-zinc-400 text-xs hidden md:table-cell">
                      {r.date ?? '—'}
                      {r.meet_name ? ` · ${r.meet_name}` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center gap-3 text-xs text-zinc-400">
            <button
              onClick={() => setUrl({ rk_page: String(page - 1) })}
              disabled={page <= 0}
              className="px-3 py-1.5 rounded border border-zinc-800 hover:border-zinc-600 disabled:text-zinc-600 disabled:border-zinc-900 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <span className="tabular-nums">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.n_total)} of{' '}
              {data.n_total}
            </span>
            <button
              onClick={() => setUrl({ rk_page: String(page + 1) })}
              disabled={page + 1 >= nPages}
              className="px-3 py-1.5 rounded border border-zinc-800 hover:border-zinc-600 disabled:text-zinc-600 disabled:border-zinc-900 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </>
      )}

      <details className="mt-2">
        <summary className="text-zinc-400 text-xs cursor-pointer hover:text-zinc-300">
          Methodology notes
        </summary>
        <div className="text-zinc-400 text-xs mt-2 space-y-1.5 max-w-2xl">
          <p>
            <span className="text-zinc-400 font-medium">Active window.</span>{' '}
            A lifter appears if they competed within 24 months of the most
            recent meet in the dataset. Anchoring to the data rather than
            today keeps the board stable if the weekly refresh stalls.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">Raw only.</span>{' '}
            IPF GL Points coefficients are defined for Raw Classic full
            power. Equipped results are excluded rather than scored with
            the wrong coefficients.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">One row per lifter.</span>{' '}
            Every column comes from that lifter's single best meet by the
            selected metric, so the total, GLP, class, and date always
            describe the same day.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">Standing.</span>{' '}
            Percentile of the lifter's GLP within the active cohort of the
            same sex. Names for these tiers are still being worked out.
          </p>
          <p>
            <span className="text-zinc-400 font-medium">Same-name lifters.</span>{' '}
            OpenIPF keys on name, so two different athletes sharing a name
            merge into one row. Rare, but it happens.
          </p>
          <p>
            Full methodology on the{' '}
            <a href="?tab=about" className="underline underline-offset-2 hover:text-zinc-300">
              About page
            </a>
            .
          </p>
        </div>
      </details>
    </div>
  )
}
