// QT coverage panel -- unified filter-driven view.
//
// Reads from /api/qt/live/* which is backed by qt_current.csv, scraped
// weekly from powerlifting.ca (federal CPU Nationals + Regionals) and
// ontariopowerlifting.org (OPA Ontario Provincials) by the qt_refresh
// GitHub Actions workflow. See data/scrapers/ + the weekly workflow
// for the pipeline.
//
// Filter panel exposes: Sex, Level (Nationals | Regionals | Provincials),
// Division, Effective year, and a conditional Region (for 2027
// Regionals) or Province (for Provincials). The output table is the
// same shape in every mode: one row per weight class with the QT, the
// cohort count in the 24-month qualifying window, and the % of that
// cohort who meet the QT.

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
type LevelT = 'Nationals' | 'Regionals' | 'Provincials'

// Provinces that publish their own provincial QTs distinct from CPU
// regionals. Enabled in the Province dropdown when Level=Provincials.
// Other provinces are served via the CPU Regional view (not this
// panel); this list grows as we confirm more provincial federations
// publish separate numbers.
const PROVINCES_WITH_OWN_QT = ['Ontario'] as const

export default function QtLiveCoveragePanel() {
  const [sex, setSex] = useState<SexT>('M')
  const [level, setLevel] = useState<LevelT>('Nationals')
  const [division, setDivision] = useState<string>('Open')
  const [effectiveYear, setEffectiveYear] = useState<number>(2027)
  const [region, setRegion] = useState<string>('')
  const [province, setProvince] = useState<string>('Ontario')

  const filtersQuery = useQuery<QtLiveFilters>({
    queryKey: ['qt-live-filters'],
    queryFn: fetchQtLiveFilters,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const regionApplies = level === 'Regionals' && effectiveYear === 2027
  const provinceApplies = level === 'Provincials'

  const coverageParams = useMemo(
    () => ({
      sex,
      level,
      effective_year: effectiveYear,
      division,
      region: regionApplies && region ? region : null,
      province: provinceApplies && province ? province : null,
    }),
    [sex, level, effectiveYear, division, region, province, regionApplies, provinceApplies],
  )

  const coverageQuery = useQuery<QtLiveCoverageResponse>({
    queryKey: ['qt-live-coverage', coverageParams],
    queryFn: () => fetchQtLiveCoverage(coverageParams),
    staleTime: 10 * 60 * 1000,
    retry: 3,
    enabled:
      filtersQuery.data?.live_data_available === true &&
      (!regionApplies || Boolean(region)) &&
      (!provinceApplies || Boolean(province)),
  })

  if (filtersQuery.isLoading) return <LoadingSkeleton lines={2} />
  if (filtersQuery.isError) {
    return <QueryErrorCard error={filtersQuery.error} onRetry={() => filtersQuery.refetch()} />
  }

  const filters = filtersQuery.data
  if (!filters || !filters.live_data_available) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-4 text-sm text-zinc-400">
        <p className="text-zinc-300 font-medium mb-1">QT data not yet available.</p>
        <p className="text-xs leading-relaxed">
          The weekly qt_refresh workflow publishes fresh CPU + OPA qualifying
          totals to the site. Until the first successful run completes, this
          view is empty. Try again in a few minutes, or check the scraper
          workflow runs on GitHub.
        </p>
      </div>
    )
  }

  const coverage = coverageQuery.data
  const rows = coverage?.rows ?? []
  const levels = (filters.levels ?? ['Nationals', 'Regionals', 'Provincials']) as LevelT[]

  // Divisions available per level. OPA publishes the same age divisions
  // as CPU, so we reuse the combined filters list.
  const divisions = filters.divisions ?? ['Open']

  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/30 p-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2 mb-1">
        <h3 className="text-zinc-100 text-base font-semibold">
          CPU qualifying-total coverage
        </h3>
        <span className="text-zinc-500 text-xs">
          Data fetched {fmtFetchedAt(filters.fetched_at)} from powerlifting.ca
          {provinceApplies && ' and ontariopowerlifting.org'}
        </span>
      </div>
      <p className="text-zinc-400 text-xs max-w-3xl">
        Percent of Canadian IPF lifters in the 24-month window ending March 1
        of the effective year whose best SBD total meets the qualifying total
        for the selected slice. CPU federal data covers Nationals and
        Regionals; Provincial coverage is currently Ontario-only (OPA) with
        other provinces rolling out as their federations' sites are audited.
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
            {levels.map((l) => (
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
            {divisions.map((d) => (
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
        {provinceApplies && (
          <label className="flex items-center gap-2">
            <span className="text-zinc-400 text-xs">Province</span>
            <select
              className="bg-zinc-900 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm"
              value={province}
              onChange={(e) => setProvince(e.target.value)}
            >
              {(filters.provinces && filters.provinces.length > 0
                ? filters.provinces
                : PROVINCES_WITH_OWN_QT).map((p) => (
                <option key={p} value={p}>{p}</option>
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
            {provinceApplies && !province && (
              <p className="text-xs text-amber-400/80 mb-2">
                Pick a province to see Provincial coverage.
              </p>
            )}
            {provinceApplies && province && rows.length === 0 && (
              <p className="text-xs text-amber-400/80 mb-2">
                No provincial QT data yet for {province}. Only Ontario (OPA)
                publishes separate provincial numbers so far; other provinces
                reuse the CPU Regional standards (switch Level to Regionals
                to see those).
              </p>
            )}
            {rows.length === 0 && !provinceApplies ? (
              <p className="text-zinc-500 text-sm">
                No live QT data for this combination.
              </p>
            ) : rows.length > 0 && (
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
