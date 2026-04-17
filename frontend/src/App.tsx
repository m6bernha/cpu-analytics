// Top-level app shell: tab header + active tab content.
//
// Tabs managed via useUrlState so the URL reflects the active tab and deep
// links are shareable. Tabs are kept mounted (display: none for inactive
// ones) so local state survives switches.

import AthleteProjection from './tabs/AthleteProjection'
import Progression from './tabs/Progression'
import QTSqueeze from './tabs/QTSqueeze'
import LifterLookup from './tabs/LifterLookup'
import { ErrorBoundary } from './lib/ErrorBoundary'
import { useUrlState } from './lib/useUrlState'

type TabKey = 'progression' | 'projection' | 'lookup' | 'qt'

// Tab order: most-used analytics first, Projection as the new BETA feature,
// Lifter Lookup for individual use, QT Squeeze last (it's the specialized
// "am I qualifying" view most users visit occasionally).
const TABS: { key: TabKey; label: string; beta?: boolean }[] = [
  { key: 'progression', label: 'Progression' },
  { key: 'projection', label: 'Athlete Projection', beta: true },
  { key: 'lookup', label: 'Lifter Lookup' },
  { key: 'qt', label: 'QT Squeeze' },
]

const VALID_TABS: TabKey[] = ['progression', 'projection', 'lookup', 'qt']

export default function App() {
  const [url, setUrl] = useUrlState({ tab: 'progression' as string })
  const tab: TabKey = VALID_TABS.includes(url.tab as TabKey)
    ? (url.tab as TabKey)
    : 'progression'
  const setTab = (t: TabKey) => setUrl({ tab: t })

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="border-b border-zinc-800 px-4 sm:px-6 py-3 sm:py-4">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-3">
          <div>
            <h1 className="text-lg sm:text-xl font-semibold">CPU Powerlifting Analytics</h1>
            <p className="text-zinc-500 text-xs">Canadian lifters, IPF-sanctioned meets</p>
          </div>
          <nav
            className="flex gap-2 -mx-1 px-1 overflow-x-auto"
            role="tablist"
            aria-label="Main tabs"
          >
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                role="tab"
                aria-selected={tab === t.key}
                className={
                  'px-3 py-1.5 rounded text-sm transition-colors whitespace-nowrap ' +
                  (tab === t.key
                    ? 'bg-zinc-800 text-zinc-100'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
                }
              >
                {t.label}
                {t.beta && (
                  <span className="ml-1 text-[9px] uppercase tracking-wider text-amber-500 align-top">
                    beta
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-6">
        <div style={{ display: tab === 'progression' ? undefined : 'none' }}>
          <ErrorBoundary label="Progression">
            <Progression />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'projection' ? undefined : 'none' }}>
          <ErrorBoundary label="Athlete Projection">
            <AthleteProjection />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'lookup' ? undefined : 'none' }}>
          <ErrorBoundary label="Lifter Lookup">
            <LifterLookup />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'qt' ? undefined : 'none' }}>
          <ErrorBoundary label="QT Squeeze">
            <QTSqueeze />
          </ErrorBoundary>
        </div>
      </main>

      <footer className="border-t border-zinc-900 mt-12 px-4 sm:px-6 py-5">
        <div className="max-w-6xl mx-auto text-zinc-500 text-xs space-y-3">
          <div className="flex flex-wrap gap-x-6 gap-y-1 items-center">
            <div className="text-zinc-400">
              Made by{' '}
              <span className="text-zinc-200 font-medium">Matthias Bernhard</span>
            </div>
            <a
              href="https://www.linkedin.com/in/matthiasbernhard/"
              target="_blank"
              rel="noreferrer"
              className="hover:text-zinc-300 underline underline-offset-2"
            >
              LinkedIn
            </a>
            <a
              href="https://www.instagram.com/mattvireo/"
              target="_blank"
              rel="noreferrer"
              className="hover:text-zinc-300 underline underline-offset-2"
            >
              Instagram
            </a>
            <a
              href="https://github.com/m6bernha/cpu-analytics"
              target="_blank"
              rel="noreferrer"
              className="hover:text-zinc-300 underline underline-offset-2"
            >
              Source on GitHub
            </a>
          </div>
          <div className="text-zinc-500">
            Thanks for using this site. If you're a CPU lifter, I hope it's
            useful. If you're a coach, I'd love to hear what else would help.
          </div>
          <div className="text-zinc-600">
            Data from{' '}
            <a
              href="https://www.openpowerlifting.org"
              target="_blank"
              rel="noreferrer"
              className="hover:text-zinc-400 underline underline-offset-2"
            >
              OpenPowerlifting
            </a>
            {' '}(CC0). Refreshed weekly from the official OpenIPF bulk export.
            This site is not affiliated with the CPU or IPF.
          </div>
        </div>
      </footer>
    </div>
  )
}
