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
import { injectAthleteMeta, summarize } from './src/lib/ogMeta.js'

export const config = { matcher: '/athlete/:path*' }

const API_BASE =
  process.env.VITE_API_BASE ?? 'https://cpu-analytics-backend.onrender.com'

// Same crawler-friendly budget as the card endpoint: a missing stat line
// costs a slightly plainer description, a slow response costs the preview.
const BACKEND_TIMEOUT_MS = 3000

function decodeName(pathname: string): string | null {
  const m = pathname.match(/^\/athlete\/(.+?)\/?$/)
  if (!m) return null
  try {
    const name = decodeURIComponent(m[1]).trim()
    return name || null
  } catch {
    return null
  }
}

export default async function middleware(request: Request) {
  const url = new URL(request.url)
  const name = decodeName(url.pathname)

  // Fetch the SPA shell. On any failure fall through to normal serving
  // rather than erroring the page: a missing preview is recoverable, a
  // blank profile page is not.
  const shellRes = await fetch(new URL('/', url)).catch(() => null)
  if (!name || !shellRes || !shellRes.ok) return

  const contentType = shellRes.headers.get('content-type') ?? ''
  if (!contentType.includes('text/html')) return

  const html = await shellRes.text().catch(() => null)
  if (!html) return

  let summary: string | null = null
  try {
    const res = await fetch(
      `${API_BASE}/api/lifters/${encodeURIComponent(name)}/history`,
      { signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) },
    )
    if (res.ok) summary = summarize(await res.json())
  } catch {
    // Cold or slow backend: keep the generic description.
  }

  const origin = `${url.protocol}//${url.host}`
  const out = injectAthleteMeta(html, {
    name,
    summary,
    url: `${origin}/athlete/${encodeURIComponent(name)}`,
    image: `${origin}/api/og/athlete?name=${encodeURIComponent(name)}`,
  })

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
