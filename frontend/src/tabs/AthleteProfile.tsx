// Public athlete profile at /athlete/{encoded-name}.
// Phase 1a of the social layer (docs/adr/0002-social-layer-stateless.md).
//
// Deliberately thin: it fetches the same payloads Lifter Lookup uses and
// composes the EXISTING LifterDetail (which already renders AthleteCard +
// percentile badge + chart + meet table + share + PNG export). The value
// here is the real, shareable URL, not new UI.
//
// LifterDetail stays a dynamic import so it keeps sharing the lazy chunk
// with Lifter Lookup instead of being pulled into the main bundle.

import { Suspense, lazy } from 'react'
import { useQuery } from '@tanstack/react-query'

import {
  fetchLifterHistory,
  fetchQtStandards,
  type LifterHistory,
  type QtStandardRow,
} from '../lib/api'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
import { ShareButton } from '../lib/ShareButton'
import { navigate } from '../lib/route'

const LifterDetail = lazy(() => import('./LifterDetail'))

export default function AthleteProfile({ name }: { name: string }) {
  const historyQuery = useQuery<LifterHistory>({
    queryKey: ['lifter-history', name],
    queryFn: () => fetchLifterHistory(name),
    enabled: !!name,
  })

  const standardsQuery = useQuery<QtStandardRow[]>({
    queryKey: ['qt-standards'],
    queryFn: fetchQtStandards,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const history = historyQuery.data

  return (
    <div className="space-y-4">
      <nav className="text-xs text-zinc-500">
        <a
          href="/?tab=rankings"
          onClick={(e) => {
            e.preventDefault()
            navigate('/?tab=rankings')
          }}
          className="hover:text-zinc-300 underline underline-offset-2"
        >
          Rankings
        </a>
        <span className="mx-2">/</span>
        <span className="text-zinc-400">{name}</span>
      </nav>

      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-zinc-100 text-xl font-semibold">{name}</h1>
        <ShareButton surface="athlete_profile" ariaLabel="Copy shareable link to this athlete" />
        <a
          href={`/?tab=projection&ap_lifter=${encodeURIComponent(name)}`}
          onClick={(e) => {
            e.preventDefault()
            navigate(`/?tab=projection&ap_lifter=${encodeURIComponent(name)}`)
          }}
          className="px-3 py-1 rounded text-xs border border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
        >
          Project this lifter
        </a>
      </div>

      {historyQuery.isError && (
        <QueryErrorCard
          error={historyQuery.error}
          onRetry={() => historyQuery.refetch()}
          label="Athlete profile"
        />
      )}
      {historyQuery.isLoading && <LoadingSkeleton lines={3} chart />}

      {history && !history.found && (
        <div className="text-sm text-zinc-300 space-y-2 max-w-2xl">
          <p>No Canadian IPF-affiliated meets found for this name.</p>
          <p className="text-zinc-500 text-xs">
            Names must match the OpenIPF spelling exactly. Try{' '}
            <a
              href="/?tab=lookup"
              onClick={(e) => {
                e.preventDefault()
                navigate('/?tab=lookup')
              }}
              className="underline underline-offset-2 hover:text-zinc-300"
            >
              searching for the lifter
            </a>{' '}
            instead.
          </p>
        </div>
      )}

      {history && history.found && (
        <Suspense fallback={<LoadingSkeleton lines={3} chart />}>
          <LifterDetail
            history={history}
            standards={standardsQuery.data}
            isActive
          />
        </Suspense>
      )}
    </div>
  )
}
