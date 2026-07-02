// Small "Data through YYYY-MM-DD" badge for the app header.
//
// Reads /api/meta/freshness (latest meet date in the parquet). If the
// latest meet is suspiciously old the badge turns amber, which doubles
// as a user-visible signal that the weekly refresh pipeline stalled.
// Renders nothing while loading or on error: the badge is decoration
// and must never add error noise to the header.

import { useQuery } from '@tanstack/react-query'
import { fetchFreshness } from './api'

// Meet results reach OpenPowerlifting with a natural lag of one to three
// weeks. 35 days means roughly two missed weekly refreshes before we warn.
const STALE_AFTER_DAYS = 35

export function FreshnessBadge() {
  const query = useQuery({
    queryKey: ['meta-freshness'],
    queryFn: fetchFreshness,
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const latestDate = query.data?.latest_meet_date
  if (!latestDate) return null

  const latestUtc = new Date(`${latestDate}T00:00:00Z`).getTime()
  if (Number.isNaN(latestUtc)) return null
  const ageDays = Math.floor((Date.now() - latestUtc) / 86_400_000)
  const isStale = ageDays > STALE_AFTER_DAYS

  return (
    <span
      className={
        'block text-[11px] mt-0.5 ' +
        (isStale ? 'text-amber-500' : 'text-zinc-600')
      }
      title="Most recent meet date in the dataset. Refreshed weekly from the OpenIPF export."
    >
      Data through {latestDate}
      {isStale && ' · refresh may be behind'}
    </span>
  )
}
