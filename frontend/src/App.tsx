// Top-level app shell: tab header + active tab content.
//
// Tabs are managed with a simple useState. Three tabs don't justify adding
// react-router. If we ever need shareable URLs per tab, swap in react-router
// then.

import Progression from './tabs/Progression'
import QTSqueeze from './tabs/QTSqueeze'
import LifterLookup from './tabs/LifterLookup'
import { useUrlState } from './lib/useUrlState'

type TabKey = 'progression' | 'qt' | 'lookup'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'progression', label: 'Progression' },
  { key: 'qt', label: 'QT Squeeze' },
  { key: 'lookup', label: 'Lifter Lookup' },
]

const VALID_TABS: TabKey[] = ['progression', 'qt', 'lookup']

export default function App() {
  const [url, setUrl] = useUrlState({ tab: 'progression' as string })
  const tab: TabKey = VALID_TABS.includes(url.tab as TabKey)
    ? (url.tab as TabKey)
    : 'progression'
  const setTab = (t: TabKey) => setUrl({ tab: t })

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="border-b border-zinc-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-baseline justify-between">
          <div>
            <h1 className="text-xl font-semibold">CPU Powerlifting Analytics</h1>
            <p className="text-zinc-500 text-xs">Canadian lifters, IPF-sanctioned meets</p>
          </div>
          <nav className="flex gap-2">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={
                  'px-3 py-1.5 rounded text-sm transition-colors ' +
                  (tab === t.key
                    ? 'bg-zinc-800 text-zinc-100'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6">
        {tab === 'progression' && <Progression />}
        {tab === 'qt' && <QTSqueeze />}
        {tab === 'lookup' && <LifterLookup />}
      </main>

      <footer className="border-t border-zinc-900 mt-12 px-6 py-4">
        <div className="max-w-6xl mx-auto text-zinc-500 text-xs flex flex-wrap gap-x-6 gap-y-1 justify-between">
          <div>
            Data from{' '}
            <a
              href="https://www.openpowerlifting.org"
              target="_blank"
              rel="noreferrer"
              className="hover:text-zinc-300 underline underline-offset-2"
            >
              OpenPowerlifting
            </a>
            {' '}(CC0). Refreshed weekly from the official OpenIPF bulk export.
          </div>
          <div>
            <a
              href="https://github.com/m6bernha/cpu-analytics"
              target="_blank"
              rel="noreferrer"
              className="hover:text-zinc-300 underline underline-offset-2"
            >
              Source on GitHub
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
