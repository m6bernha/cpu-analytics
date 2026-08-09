// Top-level app shell: tab header + active tab content.
//
// Tabs managed via useUrlState so the URL reflects the active tab and deep
// links are shareable. Tabs are kept mounted (display: none for inactive
// ones) so local state survives switches.

import { Suspense, lazy, useEffect, useRef } from 'react'

import About from './tabs/About'
import AthleteProjection from './tabs/AthleteProjection'
import Progression from './tabs/Progression'
import QTSqueeze from './tabs/QTSqueeze'
import LifterLookup from './tabs/LifterLookup'
import Rankings from './tabs/Rankings'
import Scout from './tabs/Scout'
import { WelcomeHero } from './components/WelcomeHero'
import { trackEvent } from './lib/analytics'
import { ErrorBoundary } from './lib/ErrorBoundary'
import { FreshnessBadge } from './lib/FreshnessBadge'
import { LoadingSkeleton } from './lib/QueryStatus'
import { navigate, useRoute } from './lib/route'
import { useUrlState } from './lib/useUrlState'

// Own chunk: the profile route is entered from a shared link, not from the
// default tab, so it should not weigh down first paint of the app shell.
const AthleteProfile = lazy(() => import('./tabs/AthleteProfile'))
const MeetPage = lazy(() => import('./tabs/MeetPage'))

type TabKey =
  | 'progression' | 'rankings' | 'projection' | 'lookup' | 'qt' | 'scout' | 'about'

// Tab order: most-used analytics first, Projection as the BETA feature,
// Lifter Lookup for individual use, Qualifying Totals (URL key stays 'qt'
// so old deep links keep working), then About.
const TABS: { key: TabKey; label: string; hint: string; beta?: boolean }[] = [
  { key: 'progression', label: 'Progression', hint: 'Cohort average total over a career, filterable' },
  { key: 'rankings', label: 'Rankings', hint: 'Best active Canadian lifters by IPF GL Points or total' },
  { key: 'projection', label: 'Athlete Projection', hint: 'Individual per-lift forecast with prediction intervals', beta: true },
  { key: 'lookup', label: 'Lifter Lookup', hint: 'Search any lifter, full meet history and PRs' },
  { key: 'qt', label: 'Qualifying Totals', hint: 'Live CPU + provincial qualifying total coverage' },
  { key: 'scout', label: 'Scout', hint: 'Meet scouting reports from a pasted roster', beta: true },
  { key: 'about', label: 'About', hint: 'Methodology, backtest results, references, disclaimers' },
]

const VALID_TABS: TabKey[] = [
  'progression', 'rankings', 'projection', 'lookup', 'qt', 'scout', 'about',
]

export default function App() {
  const [url, setUrl] = useUrlState({ tab: 'progression' as string })
  const tab: TabKey = VALID_TABS.includes(url.tab as TabKey)
    ? (url.tab as TabKey)
    : 'progression'

  // Legacy ?tab=lookup&lifter=X links are canonicalized to /athlete/X in
  // main.tsx before the first render, so by here the path is already right.
  const route = useRoute()
  const onAthletePage = route.kind === 'athlete'
  const onMeetPage = route.kind === 'meet'
  // Any non-shell route hides the tab stack and suppresses tab isActive.
  const onSubPage = onAthletePage || onMeetPage

  // Report the visible tab. The ref makes this fire once per actual change:
  // StrictMode double-invokes effects in dev, and any unrelated re-render
  // would otherwise re-report the same tab.
  const lastTabReported = useRef<string | null>(null)
  useEffect(() => {
    // A sub-page is a real path and reports itself as an automatic pageview.
    // Clearing the ref means returning to the shell re-reports the tab.
    if (onSubPage) {
      lastTabReported.current = null
      return
    }
    if (lastTabReported.current === tab) return
    lastTabReported.current = tab
    trackEvent('tab_viewed', { tab })
  }, [tab, onSubPage])

  // Tab clicks always return to the app shell. From a sub-page that is a
  // real navigation; from the shell it is just a query-string change.
  const setTab = (t: TabKey) => {
    if (onSubPage) navigate(t === 'progression' ? '/' : `/?tab=${t}`)
    else setUrl({ tab: t })
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:bg-zinc-900 focus:text-zinc-100 focus:px-3 focus:py-2 focus:rounded focus:border focus:border-orange-400"
      >
        Skip to content
      </a>
      <header className="border-b border-zinc-800 px-4 sm:px-6 py-3 sm:py-4">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-baseline sm:justify-between gap-3">
          <div>
            {/* No aria-label: it read "CPU Powerlifting Analytics home"
                while the link's visible text also includes the tagline
                below, so the accessible name did not contain the visible
                text and voice control could not target it (WCAG 2.5.3).
                Letting the name come from the content makes the two match
                by construction. */}
            <a
              href="/"
              className="hover:opacity-80 transition-opacity focus:outline-none focus-visible:ring focus-visible:ring-zinc-400 rounded"
            >
              <h1 className="text-lg sm:text-xl font-semibold">CPU Powerlifting Analytics</h1>
              <p className="text-zinc-400 text-xs">Canadian lifters, IPF-sanctioned meets</p>
            </a>
            <FreshnessBadge />
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
                title={t.hint}
                className={
                  'px-3 py-2 sm:py-1.5 rounded text-sm transition-colors whitespace-nowrap ' +
                  (tab === t.key
                    ? 'bg-zinc-800 text-zinc-100'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
                }
              >
                {t.label}
                {t.beta && (
                  <span className="ml-1 text-[9px] uppercase tracking-wider text-orange-500 align-top">
                    beta
                  </span>
                )}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main id="main-content" className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-6">
        {route.kind === 'athlete' && (
          <ErrorBoundary label="Athlete profile">
            <Suspense fallback={<LoadingSkeleton lines={3} chart reserveViewport />}>
              <AthleteProfile name={route.name} />
            </Suspense>
          </ErrorBoundary>
        )}

        {route.kind === 'meet' && (
          <ErrorBoundary label="Meet results">
            <Suspense fallback={<LoadingSkeleton lines={6} reserveViewport />}>
              <MeetPage name={route.name} date={route.date} />
            </Suspense>
          </ErrorBoundary>
        )}

        {/* The tab stack stays MOUNTED while a profile is open (hidden, not
            unmounted) so tab-internal state survives the round trip, matching
            the display:none convention the tabs already use between
            themselves. */}
        <div style={{ display: onSubPage ? 'none' : undefined }}>
        <WelcomeHero onNavigate={(t) => setTab(t as TabKey)} />
        <div style={{ display: tab === 'progression' ? undefined : 'none' }}>
          <ErrorBoundary label="Progression">
            <Progression isActive={!onSubPage && tab === 'progression'} />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'rankings' ? undefined : 'none' }}>
          <ErrorBoundary label="Rankings">
            <Rankings isActive={!onSubPage && tab === 'rankings'} />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'projection' ? undefined : 'none' }}>
          <ErrorBoundary label="Athlete Projection">
            <AthleteProjection isActive={!onSubPage && tab === 'projection'} />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'lookup' ? undefined : 'none' }}>
          <ErrorBoundary label="Lifter Lookup">
            <LifterLookup isActive={!onSubPage && tab === 'lookup'} />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'qt' ? undefined : 'none' }}>
          <ErrorBoundary label="Qualifying Totals">
            <QTSqueeze isActive={!onSubPage && tab === 'qt'} />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'scout' ? undefined : 'none' }}>
          <ErrorBoundary label="Scout">
            <Scout isActive={!onSubPage && tab === 'scout'} />
          </ErrorBoundary>
        </div>
        <div style={{ display: tab === 'about' ? undefined : 'none' }}>
          <ErrorBoundary label="About">
            <About isActive={!onSubPage && tab === 'about'} />
          </ErrorBoundary>
        </div>
        </div>
      </main>

      <footer className="border-t border-zinc-900 mt-12 px-4 sm:px-6 py-5">
        <div className="max-w-6xl mx-auto text-zinc-400 text-xs space-y-3">
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
          <div className="text-zinc-400">
            Thanks for using this site. If you're a CPU lifter, I hope it's
            useful. If you're a coach, I'd love to hear what else would help.
          </div>
          <div className="text-zinc-400">
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
