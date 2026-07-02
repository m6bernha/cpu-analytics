import { useEffect } from 'react'
import { type AthleteProjectionEngine, type LifterSearchResult } from '../../lib/api'
import SelectorSearch from './SearchPanel'

type LiftKey = 'total' | 'squat' | 'bench' | 'deadlift'

const HORIZONS = [3, 6, 12, 18] as const
const LIFTS: { key: LiftKey; label: string }[] = [
  { key: 'total', label: 'Total' },
  { key: 'squat', label: 'Squat' },
  { key: 'bench', label: 'Bench' },
  { key: 'deadlift', label: 'Deadlift' },
]

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
  showQt,
  setShowQt,
  availableYears,
  effectiveYear,
  setQtYear,
  qtLiveAvailable,
  engineDAvailable,
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
  showQt: boolean
  setShowQt: (v: boolean) => void
  availableYears: number[]
  effectiveYear: number | null
  setQtYear: (y: number) => void
  qtLiveAvailable: boolean
  engineDAvailable: boolean
}) {
  return (
    <section
      aria-label="Projection controls"
      className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_auto] gap-4 max-w-5xl items-start"
    >
      <div>
        <label
          htmlFor="ap-search"
          className="text-zinc-300 text-xs uppercase tracking-wide block mb-1"
        >
          Lifter
        </label>
        <SelectorSearch
          query={query}
          setQuery={setQuery}
          searchResults={searchResults}
          searchIsLoading={searchIsLoading}
          selected={selected}
          onSelect={onSelect}
          onReset={onReset}
        />
      </div>

      <div className="flex flex-wrap gap-3 items-start">
        {engineDAvailable && (
          <EngineToggle engine={engine} setEngine={setEngine} />
        )}
        <HorizonSelect
          horizon={horizon}
          setHorizon={setHorizon}
          meetCount={selected?.MeetCount ?? null}
        />
        <LiftSelect
          liftKey={liftKey}
          setLiftKey={setLiftKey}
          showQt={showQt}
          setShowQt={setShowQt}
          availableYears={availableYears}
          effectiveYear={effectiveYear}
          setQtYear={setQtYear}
          qtLiveAvailable={qtLiveAvailable}
        />
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
  meetCount,
}: {
  horizon: number
  setHorizon: (h: number) => void
  meetCount: number | null
}) {
  const isSmallN = meetCount != null && meetCount < 5
  const allowedHorizons = isSmallN ? HORIZONS.filter((h) => h <= 6) : HORIZONS

  useEffect(() => {
    if (isSmallN && horizon > 6) {
      setHorizon(6)
    }
  }, [isSmallN, horizon, setHorizon])

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
        {allowedHorizons.map((h) => (
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
  showQt,
  setShowQt,
  availableYears,
  effectiveYear,
  setQtYear,
  qtLiveAvailable,
}: {
  liftKey: LiftKey
  setLiftKey: (l: LiftKey) => void
  showQt: boolean
  setShowQt: (v: boolean) => void
  availableYears: number[]
  effectiveYear: number | null
  setQtYear: (y: number) => void
  qtLiveAvailable: boolean
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

      {liftKey === 'total' && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <span className="text-zinc-400 text-xs uppercase tracking-wide">
            QT lines
          </span>
          <div
            role="radiogroup"
            aria-label="CPU QT reference lines"
            className={
              'inline-flex bg-zinc-900 border border-zinc-800 rounded overflow-hidden ' +
              (!qtLiveAvailable ? 'opacity-60' : '')
            }
            title={
              !qtLiveAvailable
                ? 'Live QT feed unavailable; reference lines hidden.'
                : undefined
            }
          >
            <button
              type="button"
              role="radio"
              aria-checked={!showQt}
              onClick={() => setShowQt(false)}
              className={
                'px-3 py-1.5 text-xs transition-colors ' +
                (!showQt
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200')
              }
            >
              Off
            </button>
            {availableYears.map((y) => {
              const active = showQt && effectiveYear === y
              return (
                <button
                  key={y}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    setShowQt(true)
                    setQtYear(y)
                  }}
                  className={
                    'px-3 py-1.5 text-xs transition-colors border-l border-zinc-800 ' +
                    (active
                      ? 'bg-zinc-800 text-zinc-100'
                      : 'text-zinc-400 hover:text-zinc-200')
                  }
                >
                  {y}
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export { SelectorPanel, HORIZONS, LIFTS }
export type { LiftKey }
