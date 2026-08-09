// Meet result page at /meet/{encoded-name}/{date}.
// Phase 1c of the social layer (docs/adr/0002-social-layer-stateless.md).
//
// This is a RECORD, not a leaderboard. Two honesty constraints drive the
// copy here, both verified against real data:
//
//  1. The parquet is Country=Canada scoped, so an international meet shows
//     only the Canadian contingent (`canadian_scope_only`).
//  2. Placings are reproduced exactly as OpenIPF recorded them. A single
//     weight class can legitimately contain several lifters placed 1st,
//     because CPU awards per division — and at CPU Nationals 2026 two
//     lifters share Open 83 kg 1st with no column in the source data
//     distinguishing them. The page must not invent a single "winner".

import { useQuery } from '@tanstack/react-query'

import { fetchMeet, type MeetGroup, type MeetResponse } from '../lib/api'
import { LoadingSkeleton, QueryErrorCard } from '../lib/QueryStatus'
import { ShareButton } from '../lib/ShareButton'
import { fmtKg } from '../lib/format'
import { athletePath, navigate } from '../lib/route'

const SEX_LABEL: Record<string, string> = { F: 'Women', M: 'Men' }
const EVENT_LABEL: Record<string, string> = {
  SBD: 'Full power',
  B: 'Bench only',
  BD: 'Push-pull',
  SB: 'Squat + bench',
  SD: 'Squat + deadlift',
  S: 'Squat only',
  D: 'Deadlift only',
}

function groupTitle(g: MeetGroup): string {
  const bits = [
    SEX_LABEL[g.sex ?? ''] ?? g.sex ?? '—',
    g.weight_class ? `${g.weight_class} kg` : 'unclassified',
    g.equipment ?? '',
    EVENT_LABEL[g.event ?? ''] ?? g.event ?? '',
  ]
  return bits.filter(Boolean).join(' · ')
}

export default function MeetPage({ name, date }: { name: string; date: string }) {
  const meetQuery = useQuery<MeetResponse>({
    queryKey: ['meet', name, date],
    queryFn: () => fetchMeet(name, date),
    staleTime: 10 * 60 * 1000,
    retry: 3,
  })

  const meet = meetQuery.data

  return (
    <div className="space-y-4">
      <nav className="text-xs text-zinc-400">
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
        <ShareButton surface="meet_page" ariaLabel="Copy shareable link to this meet" />
      </div>

      <div className="text-zinc-400 text-xs flex flex-wrap gap-x-4 gap-y-1">
        <span>{date}</span>
        {meet?.federation && <span>{meet.federation}</span>}
        {meet?.meet_country && <span>{meet.meet_country}</span>}
        {meet?.found && (
          <span>
            {meet.n_lifters} {meet.n_lifters === 1 ? 'lifter' : 'lifters'} ·{' '}
            {meet.n_results} {meet.n_results === 1 ? 'result' : 'results'}
          </span>
        )}
      </div>

      {meetQuery.isError && (
        <QueryErrorCard
          error={meetQuery.error}
          onRetry={() => meetQuery.refetch()}
          label="Meet results"
        />
      )}
      {meetQuery.isLoading && <LoadingSkeleton lines={6} reserveViewport />}

      {meet && !meet.found && !meetQuery.isLoading && (
        <p className="text-zinc-300 text-sm max-w-2xl">
          No results found for this meet name and date. Meet links come from a
          lifter's history, so try opening the meet from an athlete's profile.
        </p>
      )}

      {meet?.found && (
        <>
          {meet.canadian_scope_only && meet.meet_country !== 'Canada' && (
            <p className="text-zinc-400 text-xs max-w-2xl rounded border border-zinc-800 bg-zinc-900/50 p-3">
              This site only holds results for Canadian lifters, so this page
              shows the Canadian contingent at this meet, not the full field.
            </p>
          )}

          <div className="space-y-6">
            {meet.groups.map((g, i) => (
              <section key={`${g.sex}-${g.equipment}-${g.event}-${g.weight_class}-${i}`}>
                <h2 className="text-zinc-200 text-sm font-medium mb-1.5">
                  {groupTitle(g)}
                  <span className="ml-2 text-zinc-400 font-normal">
                    {g.n_results} {g.n_results === 1 ? 'result' : 'results'}
                  </span>
                </h2>
                <div className="overflow-x-auto">
                  <table className="text-xs min-w-full">
                    <thead className="text-zinc-400 text-[10px] uppercase tracking-wider">
                      <tr>
                        <th className="text-right pr-3 pb-1">Pl</th>
                        <th className="text-left pr-3 pb-1">Lifter</th>
                        <th className="text-left pr-3 pb-1 hidden md:table-cell">Division</th>
                        <th className="text-right pr-3 pb-1 hidden sm:table-cell">BW</th>
                        <th className="text-right pr-3 pb-1 hidden sm:table-cell">S</th>
                        <th className="text-right pr-3 pb-1 hidden sm:table-cell">B</th>
                        <th className="text-right pr-3 pb-1 hidden sm:table-cell">D</th>
                        <th className="text-right pr-3 pb-1">Total</th>
                        <th className="text-right pr-3 pb-1 hidden md:table-cell">GLP</th>
                      </tr>
                    </thead>
                    <tbody className="text-zinc-200">
                      {g.results.map((r, j) => (
                        <tr key={`${r.name}-${j}`} className="border-t border-zinc-900">
                          <td className="pr-3 py-1 text-right tabular-nums text-zinc-400">
                            {r.place ?? '—'}
                          </td>
                          <td className="pr-3 py-1">
                            <a
                              href={athletePath(r.name)}
                              onClick={(e) => {
                                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
                                e.preventDefault()
                                navigate(athletePath(r.name))
                              }}
                              className="hover:text-orange-300 underline underline-offset-2 decoration-zinc-700"
                            >
                              {r.name}
                            </a>
                          </td>
                          <td className="pr-3 py-1 text-zinc-400 hidden md:table-cell">{r.division ?? '—'}</td>
                          <td className="pr-3 py-1 text-right tabular-nums text-zinc-400 hidden sm:table-cell">
                            {fmtKg(r.bodyweight_kg, 1)}
                          </td>
                          <td className="pr-3 py-1 text-right tabular-nums text-zinc-400 hidden sm:table-cell">
                            {fmtKg(r.squat_kg, 1)}
                          </td>
                          <td className="pr-3 py-1 text-right tabular-nums text-zinc-400 hidden sm:table-cell">
                            {fmtKg(r.bench_kg, 1)}
                          </td>
                          <td className="pr-3 py-1 text-right tabular-nums text-zinc-400 hidden sm:table-cell">
                            {fmtKg(r.deadlift_kg, 1)}
                          </td>
                          <td className="pr-3 py-1 text-right tabular-nums">
                            {fmtKg(r.total_kg, 1)}
                          </td>
                          <td className="pr-3 py-1 text-right tabular-nums text-zinc-400 hidden md:table-cell">
                            {r.glp?.toFixed(1) ?? '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ))}
          </div>

          <details className="mt-2">
            <summary className="text-zinc-400 text-xs cursor-pointer hover:text-zinc-300">
              Methodology notes
            </summary>
            <div className="text-zinc-400 text-xs mt-2 space-y-1.5 max-w-2xl">
              <p>
                <span className="text-zinc-400 font-medium">Placings are as recorded.</span>{' '}
                CPU awards placings per division, so one weight class can hold
                several lifters placed 1st. Where the source data does not
                distinguish two same-division placings, both are shown rather
                than one being dropped or picked as the winner.
              </p>
              <p>
                <span className="text-zinc-400 font-medium">Complete record.</span>{' '}
                Every event and equipment category recorded at this meet is
                listed, not just Raw full power, so nobody disappears from
                their own meet.
              </p>
              <p>
                <span className="text-zinc-400 font-medium">Canadian lifters only.</span>{' '}
                The dataset covers Canadian lifters at IPF-sanctioned meets.
              </p>
              <p>
                Full methodology on the{' '}
                <a href="?tab=about" className="underline underline-offset-2 hover:text-zinc-300">
                  About page
                </a>
                .
              </p>
            </div>
          </details>
        </>
      )}
    </div>
  )
}
