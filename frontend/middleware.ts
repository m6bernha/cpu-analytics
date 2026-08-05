// Injects per-athlete Open Graph metadata into the SPA shell for
// /athlete/* requests (ADR 0002 Phase 1b).
//
// Crawlers do not run JavaScript, so a client-rendered <title>/og:image is
// invisible to them. This fetches the built index.html at the edge and
// rewrites the tags before the response leaves the network, which gets
// per-athlete previews without server-rendering the app.
//
// Applied to humans as well as crawlers, deliberately: no user-agent
// sniffing to get wrong, and everyone gets the same HTML, which makes the
// behaviour debuggable with a plain curl.
//
// The matcher covers only /athlete/*, so fetching '/' below cannot re-enter
// this middleware.
//
// NOTE: outside `tsconfig.app.json`'s `include: ["src"]`; type-checked by
// `tsconfig.edge.json` via `npm run build`. See api/og/athlete.tsx.

// Explicit .js extension: see the note in api/og/athlete.tsx.
import { injectAthleteMeta, injectMeetMeta, summarize } from './src/lib/ogMeta.js'

export const config = { matcher: ['/athlete/:path*', '/meet/:path*'] }

const API_BASE =
  process.env.VITE_API_BASE ?? 'https://cpu-analytics-backend.onrender.com'

// Same crawler-friendly budget as the card endpoint: a missing stat line
// costs a slightly plainer description, a slow response costs the preview.
const BACKEND_TIMEOUT_MS = 3000

type Target =
  | { kind: 'athlete'; name: string }
  | { kind: 'meet'; name: string; date: string }
  | null

// Mirrors parseRoute() in src/lib/route.ts. Kept separate because the edge
// runtime must not pull in the React-facing module graph.
function parseTarget(pathname: string): Target {
  const decode = (raw: string): string | null => {
    try {
      const s = decodeURIComponent(raw).trim()
      return s || null
    } catch {
      return null
    }
  }

  const meet = pathname.match(/^\/meet\/(.+)\/(\d{4}-\d{2}-\d{2})\/?$/)
  if (meet) {
    const name = decode(meet[1])
    return name ? { kind: 'meet', name, date: meet[2] } : null
  }

  const athlete = pathname.match(/^\/athlete\/(.+?)\/?$/)
  if (athlete) {
    const name = decode(athlete[1])
    return name ? { kind: 'athlete', name } : null
  }

  return null
}

export default async function middleware(request: Request) {
  const url = new URL(request.url)
  const target = parseTarget(url.pathname)

  // Fetch the SPA shell. On any failure fall through to normal serving
  // rather than erroring the page: a missing preview is recoverable, a
  // blank page is not.
  const shellRes = await fetch(new URL('/', url)).catch(() => null)
  if (!target || !shellRes || !shellRes.ok) return

  const contentType = shellRes.headers.get('content-type') ?? ''
  if (!contentType.includes('text/html')) return

  const html = await shellRes.text().catch(() => null)
  if (!html) return

  const origin = `${url.protocol}//${url.host}`
  const enc = encodeURIComponent
  let out: string

  if (target.kind === 'meet') {
    let summary: string | null = null
    try {
      const res = await fetch(
        `${API_BASE}/api/meet?name=${enc(target.name)}&date=${enc(target.date)}`,
        { signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) },
      )
      if (res.ok) {
        const d: any = await res.json()
        if (d?.found) {
          summary =
            `${d.n_lifters} Canadian lifters · ${d.n_results} results` +
            (d.federation ? ` · ${d.federation}` : '')
        }
      }
    } catch {
      // Cold or slow backend: keep the generic description.
    }
    out = injectMeetMeta(html, {
      name: target.name,
      date: target.date,
      summary,
      url: `${origin}/meet/${enc(target.name)}/${target.date}`,
      image: `${origin}/api/og/meet?name=${enc(target.name)}&date=${enc(target.date)}`,
    })
  } else {
    let summary: string | null = null
    try {
      const res = await fetch(
        `${API_BASE}/api/lifters/${enc(target.name)}/history`,
        { signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) },
      )
      if (res.ok) summary = summarize(await res.json())
    } catch {
      // Cold or slow backend: keep the generic description.
    }
    out = injectAthleteMeta(html, {
      name: target.name,
      summary,
      url: `${origin}/athlete/${enc(target.name)}`,
      image: `${origin}/api/og/athlete?name=${enc(target.name)}`,
    })
  }

  return new Response(out, {
    status: 200,
    headers: {
      'content-type': 'text/html; charset=utf-8',
      // Short shared cache so a PR shows up in previews within the hour,
      // while repeat crawls still hit the edge.
      'cache-control': 'public, max-age=0, s-maxage=3600, stale-while-revalidate=86400',
    },
  })
}
