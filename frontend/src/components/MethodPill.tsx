// MethodPill — small badge that surfaces which projection method a chart
// uses, with a clickable info icon that opens a short methodology popover.
// Locked 2026-04-26 (plan v1 Q1) so the LL vs AP method difference is
// always visible at the chart level, not just in a methodology footer.
//
// Two variants:
// - 'lifter-lookup'      → "Linear regression — this lifter only"
// - 'athlete-projection' → "Engine C — cohort-aware Bayesian"
//
// Behavior:
// - Click the ⓘ icon to toggle the tooltip.
// - Click outside, press Escape, or toggle the icon again to close.
// - Pure presentational — no data deps, safe to mount anywhere.

import { useState, useRef, useEffect } from 'react'

export type MethodPillVariant = 'lifter-lookup' | 'athlete-projection'

const METHOD_COPY: Record<
  MethodPillVariant,
  { label: string; tooltip: string }
> = {
  'lifter-lookup': {
    label: 'Linear regression — this lifter only',
    tooltip:
      "Fits a single regression line through this lifter's meet totals over time. " +
      'No cohort comparison, no shrinkage. Simple and transparent — every projection ' +
      'is reproducible from the visible meet history alone.',
  },
  'athlete-projection': {
    label: 'Engine C — cohort-aware Bayesian',
    tooltip:
      "Combines the lifter's own Huber-fit trajectory with a cohort slope (their " +
      'age division × IPF GL bracket). Bayesian shrinkage toward the cohort prevents ' +
      'overconfident extrapolation. 95% prediction intervals via Kaplan-Meier.',
  },
}

export function MethodPill({ variant }: { variant: MethodPillVariant }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  const { label, tooltip } = METHOD_COPY[variant]

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
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full border border-zinc-800 text-xs uppercase tracking-wide text-zinc-400">
        <span className="text-zinc-500">Method ·</span>
        <span>{label}</span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label="Method details"
          aria-expanded={open}
          className="text-zinc-500 hover:text-zinc-200 ml-0.5 leading-none transition-colors focus:outline-none focus:text-zinc-200"
        >
          ⓘ
        </button>
      </span>
      {open && (
        <div
          role="tooltip"
          className="absolute z-20 left-0 mt-2 w-80 p-3 bg-zinc-900 border border-zinc-700 rounded shadow-lg text-zinc-300 text-xs leading-relaxed normal-case"
        >
          {tooltip}
        </div>
      )}
    </div>
  )
}
