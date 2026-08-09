// Reusable loading + error display for TanStack Query results.
//
// - QueryErrorCard: inline error panel with a Retry button. Surfaces the
//   HTTP status (if the error message contains one) and mentions the
//   Render free-tier cold start as the most likely cause.
// - LoadingSkeleton: a simple shimmering placeholder block. Used while
//   the first fetch is in flight, especially for QT Squeeze where the
//   cold-start response can take ~60 s.

type Props = {
  error: unknown
  onRetry?: () => void
  label?: string
}

export function QueryErrorCard({ error, onRetry, label }: Props) {
  const msg = error instanceof Error ? error.message : String(error)
  // Extract HTTP status if our api.ts wrapped it into "HTTP NNN ..."
  const statusMatch = msg.match(/HTTP (\d+)/)
  const status = statusMatch ? parseInt(statusMatch[1], 10) : null
  const isServer = status != null && status >= 500
  const isRateLimit = status === 429

  return (
    <div className="p-4 border border-red-900 bg-red-950/30 rounded text-sm max-w-2xl">
      <div className="text-red-300 font-semibold mb-1">
        {label ? `${label} failed` : 'Request failed'}
        {status != null && <span className="text-red-400 font-normal"> (HTTP {status})</span>}
      </div>
      <div className="text-red-400 text-xs mb-3">{msg}</div>

      {(isServer || status == null) && (
        <div className="text-zinc-400 text-xs mb-3">
          The backend runs on a free-tier plan and spins down after 15 minutes
          of inactivity. First requests can take up to 60 seconds while it
          wakes up. If this keeps happening after retry, the server may be
          down.
        </div>
      )}
      {isRateLimit && (
        <div className="text-zinc-400 text-xs mb-3">
          Too many requests in a short window. Wait a minute and try again.
        </div>
      )}

      {onRetry && (
        <button
          onClick={onRetry}
          className="px-3 py-1.5 bg-red-900/50 hover:bg-red-900 text-red-200 text-xs rounded border border-red-800"
        >
          Retry
        </button>
      )}
    </div>
  )
}

type SkeletonProps = {
  lines?: number
  chart?: boolean
  /**
   * Hold at least one viewport of height while loading.
   *
   * Use on WHOLE-PAGE loads (the /athlete and /meet routes), not on
   * in-page panels. Those pages replace a ~480 px skeleton with content
   * that measures ~2,200 px (profile) to ~9,100 px (meet), which shoved
   * the footer down by more than a screen and scored CLS 0.72 / 0.59 --
   * both far past the 0.25 "poor" threshold, on the very pages the
   * sitemap points search engines at.
   *
   * Reserving the fold means the footer starts below it and stays below
   * it, so the growth happens off-screen and is not a visible shift.
   * Every skeleton in one route's loading sequence must set this, or the
   * shift just moves to the handoff between two skeletons.
   */
  reserveViewport?: boolean
}

export function LoadingSkeleton({
  lines = 3,
  chart = false,
  reserveViewport = false,
}: SkeletonProps) {
  return (
    <div
      className={
        'animate-pulse space-y-2 max-w-3xl' +
        (reserveViewport ? ' min-h-screen' : '')
      }
    >
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className="h-4 bg-zinc-800 rounded"
          style={{ width: `${60 + (i % 3) * 15}%` }}
        />
      ))}
      {chart && <div className="h-80 md:h-[400px] mt-4 bg-zinc-900 border border-zinc-800 rounded" />}
    </div>
  )
}
