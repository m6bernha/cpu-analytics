// Athlete Projection (BETA) tab.
//
// Per-lift Engine C (Bayesian shrinkage + GLP-bracket cohort + Kaplan-Meier
// dropout correction) projection with a toggle for Engine D (MixedLM,
// currently delegates to shrinkage until the MixedLM wiring lands).
//
// Methodology lives on the About page (C6). The `<details>` block at the
// bottom of this tab is the short methodology note + link to About.
//
// Split into focused modules:
// - SearchPanel.tsx — lifter search box + dropdown
// - ControlPanels.tsx — engine + horizon + lift toggles
// - ProjectionChart.tsx — Recharts chart with tooltip and QT lines
// - InfoPanel.tsx — data info cards (cohort, shrinkage, uncertainty, QT proximity)
// - MethodologyBlock.tsx — collapsed methodology details

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
import {
  fetchAthleteProjection,
  fetchLifterSearch,
  fetchProjectionEngines,
  fetchQtLiveCoverage,
  fetchQtLiveFilters,
  type AthleteProjectionEngine,
  type LifterSearchResult,
  type QtLiveCoverageResponse,
} from '../lib/api'
import { useUrlState } from '../lib/useUrlState'
import { useDebouncedValue } from '../lib/useDebouncedValue'
import { MethodPill } from '../components/MethodPill'
import { Banner } from '../components/Banner'
import { SelectorPanel } from './athlete-projection/ControlPanels'
import { ProjectionChart } from './athlete-projection/ProjectionChart'
import { InfoPanel } from './athlete-projection/InfoPanel'
import MethodologyBlock from './athlete-projection/MethodologyBlock'
import type { LiftKey } from './athlete-projection/ControlPanels'

const LIFT_KEYS_STATIC = ['total', 'squat', 'bench', 'deadlift'] as const

// Find the QT kg value for a specific weight class in a live-coverage
// response. Returns undefined if the class is not present in the returned
// rows (e.g. the lifter's class is outside the scope of the published feed).
function findQtForClass(
  response: QtLiveCoverageResponse | undefined,
  weightClass: string | null | undefined,
): number | undefined {
  if (!response || !weightClass) return undefined
  const row = response.rows.find((r) => r.weight_class === weightClass)
  return row?.qt
}

export default function AthleteProjection({ isActive }: { isActive: boolean }) {
  // URL-backed state so the whole projection view (lifter + horizon + lift
  // + QT overlay) is shareable via a single paste-able link. Keys are
  // prefixed `ap_` so they cannot collide with the `lifter` key the
  // Lifter Lookup tab already owns (both tabs stay mounted behind the
  // display:none pattern, so a shared key would stomp).
  // CRITICAL: All useUrlState calls stay HERE in the orchestrator.
  // Moving state to child components would trigger collision warnings on
  // tab switches (children can mount twice in display:none mode).
  const [urlState, setUrlState] = useUrlState({
    ap_lifter: '',
    ap_horizon: '12',
    ap_lift: 'total',
    ap_show_qt: 'false',
    // Empty default picks up whatever the live QT feed reports as its
    // latest effective_year; users only see a URL key when they pin a
    // specific year.
    ap_qt_year: '',
  })

  const horizon = (() => {
    const n = Number(urlState.ap_horizon)
    return Number.isFinite(n) && n > 0 ? n : 12
  })()
  const liftKey: LiftKey = (LIFT_KEYS_STATIC as readonly string[]).includes(
    urlState.ap_lift,
  )
    ? (urlState.ap_lift as LiftKey)
    : 'total'
  const showQt = urlState.ap_show_qt === 'true'
  const urlQtYear: number | null = (() => {
    if (!urlState.ap_qt_year) return null
    const n = Number(urlState.ap_qt_year)
    return Number.isInteger(n) && n > 2000 ? n : null
  })()

  const setHorizon = useCallback(
    (h: number) => setUrlState({ ap_horizon: String(h) }),
    [setUrlState],
  )
  const setLiftKey = useCallback(
    (l: LiftKey) => setUrlState({ ap_lift: l }),
    [setUrlState],
  )
  const setShowQt = useCallback(
    (v: boolean) => setUrlState({ ap_show_qt: String(v) }),
    [setUrlState],
  )
  const setQtYear = useCallback(
    (y: number) => setUrlState({ ap_qt_year: String(y) }),
    [setUrlState],
  )

  // Engine toggle is gated off until MixedLM wiring lands (see C5 commit).
  // Keep the state so the UI stays prewired for the day it comes back.
  const [engine, setEngine] = useState<AthleteProjectionEngine>('shrinkage')

  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<LifterSearchResult | null>(null)

  // URL -> selected bootstrap. When someone pastes a shared link
  // `?tab=projection&ap_lifter=Matthias%20Bernhard`, the component mounts
  // with urlState.ap_lifter set but selected=null. Fetch the search-result
  // row for that name and auto-select so the projection query fires.
  useEffect(() => {
    const urlName = urlState.ap_lifter.trim()
    if (!urlName) {
      // URL cleared -> clear selection too (back-button, manual edit).
      if (selected) setSelected(null)
      return
    }
    if (selected?.Name === urlName) return
    let cancelled = false
    fetchLifterSearch(urlName, 1)
      .then((results) => {
        if (cancelled) return
        if (results.length > 0) {
          setSelected(results[0])
          setQuery(results[0].Name)
        }
      })
      .catch(() => {
        // Silently ignore; user can retry via the search box.
      })
    return () => {
      cancelled = true
    }
  }, [urlState.ap_lifter, selected])

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

  // Engine D global gate. Backend reports which engines are available
  // (`/api/athlete/projection-engines`). Used to decide whether to mount
  // the Simple/Advanced toggle. Cheap query, long staleTime -- the gate
  // only flips on Render redeploy after a data refresh.
  const enginesQuery = useQuery({
    queryKey: ['projection-engines'],
    queryFn: fetchProjectionEngines,
    enabled: isActive,
    staleTime: 10 * 60 * 1000,
  })
  const engineDAvailable: boolean =
    enginesQuery.data?.mixed_effects?.available ?? false

  // Live QT feed: the effective_year list populates the year picker; per-
  // (sex, level) coverage fetches resolve the actual Regionals / Nationals
  // QT kg for the lifter's class. Filter fetch is cheap and shared across
  // the two coverage queries; the coverage queries are only enabled once we
  // know which effective_year is active.
  const qtLiveFiltersQuery = useQuery({
    queryKey: ['ap-qt-live-filters'],
    queryFn: fetchQtLiveFilters,
    enabled: !!selected && isActive && showQt && liftKey === 'total',
    staleTime: 10 * 60 * 1000,
  })

  // The live filter endpoint reports every effective_year across every
  // scraper, including provincial stragglers (e.g. NLPA publishes a stale
  // 2022 list). CPU Nationals / Regionals only exist from 2026 onward
  // in the live feed; earlier years are either vendored-historical
  // (covered on Lifter Lookup) or provincial-only, so filter them out to
  // keep the Athlete Projection picker CPU-scoped.
  const availableYears: number[] = useMemo(() => {
    const raw = qtLiveFiltersQuery.data?.effective_years ?? []
    return [...raw].filter((y) => y >= 2026).sort((a, b) => a - b)
  }, [qtLiveFiltersQuery.data])
  const qtLiveAvailable = qtLiveFiltersQuery.data?.live_data_available ?? false
  // Pick the pinned URL year if it's in the published list; otherwise fall
  // back to the most recent year. null means we can't fetch coverage yet.
  const effectiveYear: number | null =
    urlQtYear != null && availableYears.includes(urlQtYear)
      ? urlQtYear
      : availableYears.length > 0
        ? availableYears[availableYears.length - 1]
        : null

  const qtSex = (selected?.Sex === 'F' ? 'F' : 'M') as 'M' | 'F'
  const qtLiveEnabled =
    !!selected &&
    isActive &&
    showQt &&
    liftKey === 'total' &&
    qtLiveAvailable &&
    effectiveYear != null

  // Regionals are split into Eastern and Western/Central CPU regions with
  // slightly different QT values per year. For BETA we show a single
  // Regionals line per the Western/Central list -- that's the region most
  // CPU members qualify through, and it matches the routing fallback the
  // QT Squeeze tab uses for BC/SK. A future revision can add a region
  // picker or fetch both to show the minimum.
  const qtRegionalsQuery = useQuery({
    queryKey: ['ap-qt-live-coverage', 'Regionals', qtSex, effectiveYear],
    queryFn: () =>
      fetchQtLiveCoverage({
        sex: qtSex,
        level: 'Regionals',
        effective_year: effectiveYear!,
        region: 'Western/Central',
      }),
    enabled: qtLiveEnabled,
    staleTime: 10 * 60 * 1000,
  })
  const qtNationalsQuery = useQuery({
    queryKey: ['ap-qt-live-coverage', 'Nationals', qtSex, effectiveYear],
    queryFn: () =>
      fetchQtLiveCoverage({
        sex: qtSex,
        level: 'Nationals',
        effective_year: effectiveYear!,
      }),
    enabled: qtLiveEnabled,
    staleTime: 10 * 60 * 1000,
  })

  const onSelectLifter = (r: LifterSearchResult) => {
    setSelected(r)
    setQuery(r.Name)
    setUrlState({ ap_lifter: r.Name })
  }

  const resetSelection = () => {
    setSelected(null)
    setQuery('')
    setUrlState({ ap_lifter: '' })
  }

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-zinc-100 text-lg font-semibold flex items-baseline gap-2">
          Athlete Projection
          <span className="text-orange-500 text-xs uppercase tracking-wide">
            Beta
          </span>
        </h2>
        <p className="text-zinc-400 text-sm mt-1 max-w-3xl">
          Pick a lifter, pick a horizon, see where their Squat, Bench, Deadlift,
          and Total are projected to land with a 95 percent prediction interval.
          Combines the lifter's own trajectory (Huber regression) with a cohort
          slope for their age division and IPF GL Points bracket.
        </p>
        <div className="mt-3">
          <MethodPill
            variant="athlete-projection"
            currentLifter={selected?.Name ?? null}
          />
        </div>
      </header>

      <SelectorPanel
        selected={selected}
        query={query}
        setQuery={setQuery}
        searchResults={searchQuery.data ?? []}
        searchIsLoading={searchQuery.isLoading && debouncedQuery.trim().length >= 2}
        onSelect={onSelectLifter}
        onReset={resetSelection}
        engine={engine}
        setEngine={setEngine}
        horizon={horizon}
        setHorizon={setHorizon}
        liftKey={liftKey}
        setLiftKey={setLiftKey}
        showQt={showQt}
        setShowQt={setShowQt}
        availableYears={availableYears}
        effectiveYear={effectiveYear}
        setQtYear={setQtYear}
        qtLiveAvailable={qtLiveAvailable}
        engineDAvailable={engineDAvailable}
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
        <div className="mt-6">
          <div className="flex flex-col gap-2 mb-3">
            {projectionQuery.data.meta?.small_n_warning && (
              <Banner tone="warning">
                Fewer than 5 meets in this lifter's history. Projection is directionally
                informative only. Server clamped horizon to 6 months.
              </Banner>
            )}
            {projectionQuery.data.meta?.long_horizon_warning && horizon > 12 && (
              <Banner tone="warning">
                Horizons past 12 months widen fast. Treat the 18-month band as the
                outer limit of plausibility, not a forecast.
              </Banner>
            )}
            {projectionQuery.data.horizon_capped && !projectionQuery.data.meta?.small_n_warning && (
              <Banner tone="info">
                Horizon capped server-side to {projectionQuery.data.horizon_months} months.
              </Banner>
            )}
            {(projectionQuery.data.outlier_lifts ?? []).length > 0 && (
              <Banner tone="warning">
                Most recent meet appears anomalous on{' '}
                <span className="font-medium">
                  {(projectionQuery.data.outlier_lifts ?? []).join(', ')}
                </span>
                . Projection uses the Huber-fit trend and best-of-last-3 current level.
              </Banner>
            )}
            {projectionQuery.data.engine === 'mixed_effects' && projectionQuery.data.meta?.engine_d_available === false && (
              <Banner tone="info">
                Advanced (MixedLM) engine wiring is still in progress. Numbers shown
                here are the Simple engine fallback.
              </Banner>
            )}
          </div>

          <ProjectionChart
            data={projectionQuery.data}
            liftKey={liftKey}
            isActive={isActive}
            showQt={showQt}
            effectiveYear={effectiveYear}
            regionalsQtKg={findQtForClass(
              qtRegionalsQuery.data,
              selected.LatestWeightClass,
            )}
            nationalsQtKg={findQtForClass(
              qtNationalsQuery.data,
              selected.LatestWeightClass,
            )}
          />

          <InfoPanel
            data={projectionQuery.data}
            liftKey={liftKey}
            showQt={showQt}
            effectiveYear={effectiveYear}
            regionalsQt={findQtForClass(
              qtRegionalsQuery.data,
              selected.LatestWeightClass,
            )}
            nationalsQt={findQtForClass(
              qtNationalsQuery.data,
              selected.LatestWeightClass,
            )}
          />
        </div>
      )}

      {selected && projectionQuery.data && !projectionQuery.data.found && (
        <div className="mt-6 p-4 border border-orange-900/40 bg-orange-950/20 rounded max-w-3xl text-orange-300 text-sm">
          No projection available: {projectionQuery.data.reason ?? 'unknown reason'}.
          A projection needs at least one SBD meet with age + bodyweight populated.
        </div>
      )}

      <MethodologyBlock />
    </div>
  )
}


