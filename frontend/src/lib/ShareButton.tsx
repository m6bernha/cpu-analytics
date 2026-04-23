// Small copy-to-clipboard button used by tabs that have URL-backed state.
//
// Click copies window.location.href so the user can paste a deep link into
// chat/social. Falls back to a temporary textarea + document.execCommand
// for insecure-context or pre-user-gesture browsers where the async
// navigator.clipboard.writeText promise rejects.

import { useState } from 'react'

export function ShareButton({
  label = 'Share',
  copiedLabel = 'Copied!',
  ariaLabel = 'Copy shareable link to this view',
  className,
}: {
  label?: string
  copiedLabel?: string
  ariaLabel?: string
  className?: string
}) {
  const [copied, setCopied] = useState<boolean>(false)

  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
      return
    } catch {
      // Fall through to the textarea fallback below.
    }
    const ta = document.createElement('textarea')
    ta.value = window.location.href
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Give up silently; the URL is still visible in the address bar.
    }
    document.body.removeChild(ta)
  }

  const base =
    'px-3 py-2 text-xs rounded border transition-colors ' +
    (copied
      ? 'text-emerald-300 border-emerald-800 bg-emerald-950/30'
      : 'text-zinc-400 border-zinc-700 hover:text-zinc-200 hover:bg-zinc-800')

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={ariaLabel}
      className={className ? `${base} ${className}` : base}
    >
      {copied ? copiedLabel : label}
    </button>
  )
}
