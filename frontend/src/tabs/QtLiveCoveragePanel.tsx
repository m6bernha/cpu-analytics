// Live QT coverage panel (2026+).
//
// Reads from /api/qt/live/* which is backed by qt_current.csv, scraped
// weekly from powerlifting.ca by the qt_refresh GitHub Actions workflow.
// Historical (pre-2025 / 2025) data stays in the four-block view below
// this panel.
//
// Shipped as a Phase 1c MVP — the full QTSqueeze UX rebuild (single
// filter-panel-driven view replacing the 4 blocks) is queued as a
// follow-up session. This panel proves the live-scrape pipeline end to
// end so the data is usable before the visual redesign lands.

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchQtLiveCoverage,
  fetchQtLiveFilters,
  type QtLiveCoverageResponse,
  type QtLiveFilters,
} from '../lib/api'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toFixed(2) + '%'
}

function fmtFetchedAt(iso: string | null | undefined): string {
  if (!iso) return 'unknown'
  return iso.slice(0, 10)
}

type SexT = 'M' | 'F'
type LevelT = 'Nationals' | 'Regionals'

export default function QtLiveCoveragePanel() {
  const [sex, setSex] = useState<SexT>('M')
  const [level, setLevel] = useState<LevelT>('Nationals')
  const [division, setDivision] = useState<string>('Open')
  const [effectiveYear, setEffectiveYear] = useState<number>(2027)
  const [region, setRegion] = useState<string>('')  // empty = no split

  const filtersQuery = useQuery<QtLiveFilters>({
    queryKey: ['qt-live-filters'],
    queryFn: fetchQtLiveFilters,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  // Region is only meaningful for 2027 Regionals. Other combos don't
  // have a split; we force region='' (NULL) in the backend query.
  const regionApplies = level === 'Regionals' && effectiveYear === 2027

  const coverageParams = useMemo(
    () => ({
      sex,
      level,
      effective_year: effectiveYear,
      division,
      region: regionApplies && region ? region : null,
    }),
    [sex, level, effectiveYear, division, region, regionApplies],
  )

  const coverageQuery = useQuery<QtLiveCoverageResponse>({
    queryKey: ['qt-live-coverage', coverageParams],
    queryFn: () => fetchQtLiveCoverage(coverageParams),
    staleTime: 10 * 60 * 1000,
    retry: 3,
    enabled: filtersQuery.data?.live_data_available === true,
  })

  if (filtersQuery.isLoading) {
    return <LoadingSkeleton lines={2} />
  }
  if (filtersQuery.isError) {
    return <QueryErrorCard error={filtersQuery.error} onRetry={() => filtersQuery.refetch()} />
  }

  const filters = filtersQuery.data
  if (!filters || !filters.live_data_available) {
    // Degraded mode: scraper hasn't published yet. Show a light banner
    // so users know the live view is coming, and fall through to the
    // historical 4-block view below.
    return (
      <div className="mb-6 rounded border border-zinc-800 bg-zinc-900/40 p-3 text-xs text-zinc-400">
        <span className="text-zinc-300 font-medium">Live data not yet available.</span>{' '}
        The weekly qt_refresh workflow publishes updated Canadian qualifying
        totals to the site. Until the first successful run completes, this
        panel is hidden. The historical coverage view below is unaffected.
      </div>
    )
  }

  const coverage = coverageQuery.data
  const rows = coverage?.rows ?? []

  return (
    <div className="mb-8 rounded border border-zinc-800 bg-zinc-900/30 p-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h3 className="text-zinc-100 text-base font-semibold">
          Live coverage (2026+)
        </h3>
        <span className="text-zinc-500 text-xs">
          Data fetched {fmtFetchedAt(filters.fetched_at)} from powerlifting.ca
        </span>
      </div>
      <p className="text-zinc-400 text-xs mt-1 max-w-3xl">
        Percent of Canadian IPF lifters in the 24-month window ending March 1
        of the effective year whose best SBD total meets the CPU qualifying
        total for that slice.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-zinc-400 text-xs">Sex</span>
          <select
            className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm"
            value={sex}
            onChange={(e) => setSex(e.target.value as SexT)}
          >
            {(filters.sexes ?? ['M', 'F']).map((s) => (
              <option key={s} value={s}>{s === 'M' ? 'Men' : 'Women'}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-zinc-400 text-xs">Level</span>
          <select
            className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm"
            value={level}
            onChange={(e) => setLevel(e.target.value as LevelT)}
          >
            {(filters.levels ?? ['Nationals', 'Regionals']).map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-zinc-400 text-xs">Division</span>
          <select
            className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm"
            value={division}
            onChange={(e) => setDivision(e.target.value)}
          >
            {(filters.divisions ?? ['Open']).map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-zinc-400 text-xs">Effective year</span>
          <select
            className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm"
            value={effectiveYear}
            onChange={(e) => setEffectiveYear(Number(e.target.value))}
          >
            {(filters.effective_years ?? [2026, 2027]).map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </label>
        {regionApplies && (
          <label className="flex items-center gap-2">
            <span className="text-zinc-400 text-xs">Region</span>
            <select
              className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            >
              <option value="">Select region</option>
              {(filters.regions ?? []).map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="mt-4">
        {coverageQuery.isLoading && <LoadingSkeleton lines={3} />}
        {coverageQuery.isError && (
          <QueryErrorCard
            error={coverageQuery.error}
            onRetry={() => coverageQuery.refetch()}
          />
        )}
        {!coverageQuery.isLoading && !coverageQuery.isError && (
          <>
            {regionApplies && !region && (
              <p className="text-xs text-amber-400/80 mb-2">
                Pick a region to see 2027 Regionals coverage.
              </p>
            )}
            {rows.length === 0 ? (
              <p className="text-zinc-500 text-sm">
                No live QT data for this combination.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-zinc-400 text-xs">
                      <th className="text-left py-1.5 pr-4">Weight class</th>
                      <th className="text-right py-1.5 pr-4">QT (kg)</th>
                      <th className="text-right py-1.5 pr-4">Lifters in window</th>
                      <th className="text-right py-1.5 pr-4">Meeting QT</th>
                      <th className="text-right py-1.5">% meeting</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.weight_class} className="border-t border-zinc-800/60">
                        <td className="py-1.5 pr-4 text-zinc-100">{r.weight_class}</td>
                        <td className="py-1.5 pr-4 text-right text-zinc-300 tabular-nums">
                          {r.qt.toFixed(1)}
                        </td>
                        <td className="py-1.5 pr-4 text-right text-zinc-400 tabular-nums">
                          {r.n_lifters}
                        </td>
                        <td className="py-1.5 pr-4 text-right text-zinc-400 tabular-nums">
                          {r.n_meeting_qt}
                        </td>
                        <td className="py-1.5 text-right text-zinc-100 tabular-nums">
                          {fmtPct(r.pct_meeting_qt)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
