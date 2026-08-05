// Per-meet Open Graph card, 1200x630 (ADR 0002 Phase 1c).
//
// GET /api/og/meet?name=<meet name>&date=<YYYY-MM-DD>
//
// Same contract as api/og/athlete.tsx: short backend timeout, branded
// fallback rather than a failed request, 24 h cache. See that file for
// the reasoning and for the tsconfig note.

import { ImageResponse } from '@vercel/og'

export const config = { runtime: 'edge' }

const API_BASE =
  process.env.VITE_API_BASE ?? 'https://cpu-analytics-backend.onrender.com'

const BACKEND_TIMEOUT_MS = 3000
const CACHE_CONTROL =
  'public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800'

const COLORS = {
  bg: '#09090b',
  panel: '#18181b',
  border: '#3f3f46',
  text: '#f4f4f5',
  muted: '#a1a1aa',
  dim: '#71717a',
  accent: '#FB923C',
}

async function loadMeet(name: string, date: string) {
  try {
    const res = await fetch(
      `${API_BASE}/api/meet?name=${encodeURIComponent(name)}&date=${encodeURIComponent(date)}`,
      { signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) },
    )
    if (!res.ok) return null
    const d: any = await res.json()
    if (!d?.found) return null
    return {
      nLifters: typeof d.n_lifters === 'number' ? d.n_lifters : null,
      nResults: typeof d.n_results === 'number' ? d.n_results : null,
      federation: d.federation ?? null,
      country: d.meet_country ?? null,
    }
  } catch {
    return null
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
        minWidth: 260,
      }}
    >
      <div style={{ fontSize: 22, color: COLORS.dim, letterSpacing: 2 }}>{label}</div>
      <div style={{ fontSize: 56, color: COLORS.text, fontWeight: 700 }}>{value}</div>
    </div>
  )
}

export default async function handler(request: Request) {
  const url = new URL(request.url)
  const name = (url.searchParams.get('name') ?? '').trim().slice(0, 120)
  const date = (url.searchParams.get('date') ?? '').trim().slice(0, 10)
  if (!name || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return new Response('missing or malformed name/date', { status: 400 })
  }

  const data = await loadMeet(name, date)

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
              fontSize: name.length > 26 ? 68 : 88,
              color: COLORS.text,
              fontWeight: 700,
              marginTop: 12,
            }}
          >
            {name}
          </div>
          <div style={{ display: 'flex', fontSize: 34, color: COLORS.muted, marginTop: 8 }}>
            {date}
            {data?.federation ? `  ·  ${data.federation}` : ''}
            {data?.country ? `  ·  ${data.country}` : ''}
          </div>
        </div>

        {data ? (
          <div style={{ display: 'flex', gap: 20 }}>
            <Stat
              label="CANADIAN LIFTERS"
              value={data.nLifters != null ? String(data.nLifters) : '—'}
            />
            <Stat
              label="RESULTS"
              value={data.nResults != null ? String(data.nResults) : '—'}
            />
          </div>
        ) : (
          <div style={{ display: 'flex', fontSize: 32, color: COLORS.muted }}>
            Full Canadian results, every division and event
          </div>
        )}

        <div style={{ display: 'flex', fontSize: 26, color: COLORS.dim }}>
          cpu-analytics.vercel.app
        </div>
      </div>
    ),
    { width: 1200, height: 630, headers: { 'cache-control': CACHE_CONTROL } },
  )
}
