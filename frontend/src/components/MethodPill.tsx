// MethodPill — clickable cross-tab method picker.
//
// Surfaces the projection-method difference between Lifter Lookup (linear
// regression on the lifter alone) and Athlete Projection (Engine C
// cohort-aware Bayesian), with Engine D MixedLM listed as a future option.
// Clicking the pill opens a popover that lists all three methods with the
// active one highlighted; picking another method navigates to the
// appropriate tab while preserving the currently-viewed lifter.
//
// Locked 2026-04-26 evening (plan v1 Q1 refinement). Replaces the prior
// passive info-icon pill — Matthias asked for a method picker, not just a
// labelled tooltip.

import { useState, useRef, useEffect } from 'react'

export type MethodPillVariant = 'lifter-lookup' | 'athlete-projection'

type MethodOption = {
  key: 'linear' | 'engine-c' | 'engine-d'
  label: string
  short: string
  description: string
  matchesVariant?: MethodPillVariant
  disabled?: boolean
  disabledReason?: string
}

const METHOD_OPTIONS: MethodOption[] = [
  {
    key: 'linear',
    label: 'Linear regression',
    short: 'this lifter only',
    description:
      "Fits a single regression line through this lifter's meet totals over time. " +
      'No cohort comparison, no shrinkage. Simple and transparent.',
    matchesVariant: 'lifter-lookup',
  },
  {
    key: 'engine-c',
    label: 'Engine C — Bayesian',
    short: 'cohort-aware',
    description:
      "Combines the lifter's own Huber-fit trajectory with a cohort slope " +
      '(age division × IPF GL bracket). Bayesian shrinkage prevents ' +
      'overconfident extrapolation. 95% PI via Kaplan-Meier.',
    matchesVariant: 'athlete-projection',
  },
  {
    key: 'engine-d',
    label: 'Engine D — MixedLM',
    short: 'multilevel fit',
    description:
      'Mixed-effects linear model that derives the cohort slope from a ' +
      'multilevel fit (random intercept + slope per lifter). Falls back ' +
      'per-lift to Engine C when a cell did not converge in the ' +
      'precompute. Available only when the live precompute clears 90%.',
    // disabled is set per-render from the engineDAvailable prop.
  },
]

const COPY: Record<MethodPillVariant, { label: string }> = {
  'lifter-lookup': { label: 'Linear regression — this lifter only' },
  'athlete-projection': { label: 'Engine C — cohort-aware Bayesian' },
}

// Build a same-page URL that switches tab + carries the current lifter into
// the destination tab's lifter URL key. Reads window.location.search at
// click time so we always merge against whatever else is in the URL (era,
// view_mode, etc.).
function buildHref(target: 'linear' | 'engine-c', lifter?: string | null): string {
  const params = new URLSearchParams(window.location.search)
  if (target === 'linear') {
    params.set('tab', 'lookup')
    if (lifter) params.set('lifter', lifter)
    params.delete('ap_lifter')
  } else if (target === 'engine-c') {
    params.set('tab', 'projection')
    if (lifter) params.set('ap_lifter', lifter)
    params.delete('lifter')
  }
  return '?' + params.toString()
}

export function MethodPill({
  variant,
  currentLifter,
  engineDAvailable = false,
}: {
  variant: MethodPillVariant
  currentLifter?: string | null
  engineDAvailable?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  const { label } = COPY[variant]

  // Engine D entry's disabled state is driven by the live availability
  // gate, not hardcoded. When the backend reports `mixed_effects.available
  // === false`, the entry shows in the popover but is non-actionable with
  // a "convergence below 90%" hint.
  const options: MethodOption[] = METHOD_OPTIONS.map((opt) =>
    opt.key === 'engine-d'
      ? {
          ...opt,
          disabled: !engineDAvailable,
          disabledReason: engineDAvailable
            ? undefined
            : 'Live precompute below 90% convergence.',
        }
      : opt,
  )

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={ref} className="inline-block relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label="Switch projection method"
        title="Switch projection method"
        className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border border-zinc-800 text-xs uppercase tracking-wide text-zinc-400 hover:text-zinc-200 hover:border-zinc-700 transition-colors focus:outline-none focus:border-zinc-600"
      >
        <span className="text-zinc-500">Method ·</span>
        <span>{label}</span>
        <span className="text-zinc-500 ml-0.5 leading-none">▾</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute z-20 left-0 mt-2 w-96 p-2 bg-zinc-900 border border-zinc-700 rounded shadow-lg normal-case"
        >
          <div className="text-zinc-500 text-[10px] uppercase tracking-wide px-2 pt-1 pb-2">
            Projection method
          </div>
          {options.map((opt) => {
            const isActive = opt.matchesVariant === variant
            const isNav =
              !opt.disabled && !isActive && opt.matchesVariant !== undefined
            const baseRow =
              'block w-full text-left px-2 py-2 rounded transition-colors '
            const stateClass = opt.disabled
              ? 'opacity-50 cursor-not-allowed'
              : isActive
                ? 'bg-zinc-800 text-zinc-100'
                : 'hover:bg-zinc-800 text-zinc-300'
            const content = (
              <>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium">{opt.label}</span>
                  <span className="text-zinc-500 text-[10px] uppercase tracking-wide shrink-0">
                    {isActive ? 'Current' : opt.short}
                  </span>
                </div>
                <div className="text-zinc-400 text-xs mt-1 leading-relaxed">
                  {opt.description}
                </div>
                {opt.disabled && opt.disabledReason && (
                  <div className="text-zinc-500 text-[10px] italic mt-1">
                    {opt.disabledReason}
                  </div>
                )}
              </>
            )
            if (isNav && (opt.key === 'linear' || opt.key === 'engine-c')) {
              return (
                <a
                  key={opt.key}
                  href={buildHref(opt.key, currentLifter)}
                  role="menuitem"
                  className={baseRow + stateClass}
                  onClick={() => setOpen(false)}
                >
                  {content}
                </a>
              )
            }
            return (
              <div
                key={opt.key}
                role="menuitem"
                aria-disabled={opt.disabled || isActive}
                className={baseRow + stateClass}
              >
                {content}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
