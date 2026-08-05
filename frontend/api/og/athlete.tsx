// Per-athlete Open Graph card, 1200x630 (ADR 0002 Phase 1b).
//
// GET /api/og/athlete?name=<exact OpenIPF name>
//
// Runs on the Edge runtime. Pulls numbers from the public backend with a
// SHORT timeout: the backend is on Render's free tier and can take up to
// 50 s to wake, while social crawlers give up in roughly 5-10 s. A plainer
// branded card always beats a broken preview, so on timeout or error this
// falls back to a name-only card rather than failing the request.
//
// NOTE: this file is outside `tsconfig.app.json`'s `include: ["src"]`. It
// is type-checked by `tsconfig.edge.json`, which `npm run build` runs, so
// CI covers it. Vercel compiles it at deploy using the compilerOptions in
// the ROOT tsconfig.json — keep those two in sync or the deploy fails on
// options no local gate exercises.

import { ImageResponse } from '@vercel/og'

// Explicit .js extension: Vercel may compile this file under node16
// module resolution, which rejects extensionless relative imports. The
// extension is also valid under bundler resolution, so it works either way.
import { percentileFor, formatPercentile } from '../../src/lib/percentile.js'

export const config = { runtime: 'edge' }

const API_BASE =
  process.env.VITE_API_BASE ?? 'https://cpu-analytics-backend.onrender.com'

// Crawler-friendly budget. See the module comment.
const BACKEND_TIMEOUT_MS = 3000

// 24 h: the data pipeline refreshes weekly, so a card regenerates well
// within a day of a lifter hitting a new PR. Overrides @vercel/og's
// 1-year immutable default, which would freeze numbers in shared links.
const CACHE_CONTROL = 'public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800'

const COLORS = {
  bg: '#09090b',        // zinc-950
  panel: '#18181b',     // zinc-900
  border: '#3f3f46',    // zinc-700
  text: '#f4f4f5',      // zinc-100
  muted: '#a1a1aa',     // zinc-400
  dim: '#71717a',       // zinc-500
  accent: '#FB923C',    // coral, the only orange-family accent sitewide
}

async function loadAthlete(name: string) {
  const signal = AbortSignal.timeout(BACKEND_TIMEOUT_MS)
  const [historyRes, curvesRes] = await Promise.allSettled([
    fetch(`${API_BASE}/api/lifters/${encodeURIComponent(name)}/history`, { signal }),
    fetch(`${API_BASE}/api/rankings/percentiles`, { signal }),
  ])

  let history: any = null
  if (historyRes.status === 'fulfilled' && historyRes.value.ok) {
    history = await historyRes.value.json().catch(() => null)
  }
  if (!history?.found) return null

  const meets: any[] = Array.isArray(history.meets) ? history.meets : []
  const glps = meets
    .map((m) => m?.Goodlift)
    .filter((v: unknown): v is number => typeof v === 'number' && v > 0)
  const bestGlp = glps.length ? Math.max(...glps) : null

  let standing: string | null = null
  if (curvesRes.status === 'fulfilled' && curvesRes.value.ok && bestGlp != null) {
    const curves = await curvesRes.value.json().catch(() => null)
    const curve = curves?.curves?.[history.sex ?? '']
    standing = formatPercentile(percentileFor(bestGlp, curve))
  }

  return {
    bestTotal: typeof history.best_total_kg === 'number' ? history.best_total_kg : null,
    weightClass: history.latest_weight_class ?? null,
    sex: history.sex ?? null,
    meetCount: typeof history.meet_count === 'number' ? history.meet_count : meets.length,
    bestGlp,
    standing,
  }
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: COLORS.panel,
        border: `1px solid ${COLORS.border}`,
        borderRadius: 12,
        padding: '20px 28px',
        minWidth: 240,
      }}
    >
      <div style={{ fontSize: 22, color: COLORS.dim, letterSpacing: 2 }}>{label}</div>
      <div style={{ fontSize: 56, color: COLORS.text, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

export default async function handler(request: Request) {
  const name = (new URL(request.url).searchParams.get('name') ?? '').trim().slice(0, 80)
  if (!name) {
    return new Response('missing name', { status: 400 })
  }

  let data: Awaited<ReturnType<typeof loadAthlete>> = null
  try {
    data = await loadAthlete(name)
  } catch {
    // Timeout / network / cold backend: fall through to the name-only card.
    data = null
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          backgroundColor: COLORS.bg,
          padding: 64,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', fontSize: 26, color: COLORS.accent, letterSpacing: 3 }}>
            CPU POWERLIFTING ANALYTICS
          </div>
          <div
            style={{
              display: 'flex',
              fontSize: data && name.length > 22 ? 76 : 92,
              color: COLORS.text,
              fontWeight: 700,
              marginTop: 12,
            }}
          >
            {name}
          </div>
          {data?.standing && (
            <div style={{ display: 'flex', fontSize: 34, color: COLORS.accent, marginTop: 10 }}>
              {data.standing} in Canada
            </div>
          )}
        </div>

        {data ? (
          <div style={{ display: 'flex', gap: 20 }}>
            <Stat
              label="BEST TOTAL"
              value={data.bestTotal != null ? `${data.bestTotal} kg` : '—'}
            />
            <Stat label="CLASS" value={data.weightClass ? `${data.weightClass} kg` : '—'} />
            <Stat
              label="IPF GL"
              value={data.bestGlp != null ? data.bestGlp.toFixed(1) : '—'}
            />
          </div>
        ) : (
          <div style={{ display: 'flex', fontSize: 32, color: COLORS.muted }}>
            Meet history, progression, and qualifying-total standing
          </div>
        )}

        <div style={{ display: 'flex', fontSize: 26, color: COLORS.dim }}>
          cpu-analytics.vercel.app
          {data?.meetCount ? `  ·  ${data.meetCount} meets` : ''}
        </div>
      </div>
    ),
    {
      width: 1200,
      height: 630,
      headers: { 'cache-control': CACHE_CONTROL },
    },
  )
}
