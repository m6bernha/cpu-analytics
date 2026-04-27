import type { ReactNode } from 'react'

export type BannerTone = 'warning' | 'info'

const TONE_CLASSES: Record<BannerTone, string> = {
  warning: 'border-orange-900/40 bg-orange-950/20 text-orange-300',
  info: 'border-zinc-800 bg-zinc-900/40 text-zinc-300',
}

export function Banner({
  tone,
  children,
}: {
  tone: BannerTone
  children: ReactNode
}) {
  return (
    <div className={`p-3 border ${TONE_CLASSES[tone]} rounded text-sm max-w-3xl`}>
      {children}
    </div>
  )
}
