// First-visit welcome panel with three start-here cards.
//
// Shown until the visitor dismisses it (flag in localStorage). Gives a
// cold visitor an immediate answer to "what is this site and where do I
// start" instead of dropping them straight into a filter panel.

import { useState } from 'react'

const STORAGE_KEY = 'cpu-welcome-dismissed'

interface StartCard {
  tab: string
  title: string
  body: string
}

const CARDS: StartCard[] = [
  {
    tab: 'lookup',
    title: 'Find yourself',
    body: 'Search your name to see every meet, PR flags, and your history against the qualifying total lines.',
  },
  {
    tab: 'progression',
    title: 'See how lifters like you progress',
    body: 'Average total over a career for your cohort. Filter by sex, weight class, age division, and more.',
  },
  {
    tab: 'qt',
    title: 'Check the qualifying totals',
    body: 'Live CPU and provincial standards, plus the share of each weight class that currently qualifies.',
  },
]

interface WelcomeHeroProps {
  onNavigate: (tab: string) => void
}

export function WelcomeHero({ onNavigate }: WelcomeHeroProps) {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1'
    } catch {
      // Storage unavailable (private mode etc): skip the hero rather
      // than show it on every render forever.
      return true
    }
  })

  if (dismissed) return null

  const dismiss = () => {
    try {
      localStorage.setItem(STORAGE_KEY, '1')
    } catch {
      // Best effort only.
    }
    setDismissed(true)
  }

  return (
    <section
      aria-label="Getting started"
      className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4 sm:p-5"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-zinc-100 text-base font-semibold">
            Free analytics for Canadian raw powerlifters
          </h2>
          <p className="text-zinc-400 text-sm mt-1 max-w-2xl">
            Built on the weekly OpenPowerlifting export of every
            IPF-sanctioned Canadian meet. Pick a starting point:
          </p>
        </div>
        <button
          onClick={dismiss}
          className="text-zinc-500 hover:text-zinc-200 text-xs whitespace-nowrap focus:outline-none focus-visible:ring focus-visible:ring-zinc-400 rounded px-1"
          aria-label="Dismiss getting started panel"
        >
          Hide this
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4">
        {CARDS.map((c) => (
          <button
            key={c.tab}
            onClick={() => onNavigate(c.tab)}
            className="text-left rounded-md border border-zinc-800 bg-zinc-950 p-3 hover:border-[#569cd6] hover:bg-zinc-900 transition-colors focus:outline-none focus-visible:ring focus-visible:ring-zinc-400"
          >
            <div className="text-zinc-100 text-sm font-medium">{c.title}</div>
            <div className="text-zinc-500 text-xs mt-1 leading-relaxed">{c.body}</div>
          </button>
        ))}
      </div>
    </section>
  )
}
