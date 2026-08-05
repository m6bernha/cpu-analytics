// Per-athlete Open Graph metadata injection (ADR 0002 Phase 1b).
//
// Kept as a PURE string transform, separate from middleware.ts, so it is
// unit-testable without an edge runtime. The middleware fetches the built
// index.html and runs it through injectAthleteMeta().
//
// Why replace rather than append: index.html already ships site-wide og:*
// and twitter:* tags. Appending a second og:title leaves two competing
// values and crawlers pick unpredictably, so every tag we own is stripped
// first and re-emitted once.

export interface AthleteMeta {
  name: string
  /** Absolute URL of the generated card image. */
  image: string
  /** Absolute canonical URL of the profile page. */
  url: string
  /** Optional one-line stat summary; falls back to a generic line. */
  summary?: string | null
  /** Used by injectMeetMeta to reuse this transform with its own title. */
  titleOverride?: string
  imageAltOverride?: string
}

// Tags this module owns end-to-end. Anything not listed here (charset,
// viewport, favicon, og:type, twitter:card) is left untouched.
const OWNED_META = [
  'og:title',
  'og:description',
  'og:url',
  'og:image',
  'og:image:alt',
  'twitter:title',
  'twitter:description',
  'twitter:image',
]

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function stripOwnedTags(html: string): string {
  let out = html
  for (const key of OWNED_META) {
    // Matches both property="..." and name="..." spellings, any attribute order.
    const re = new RegExp(
      `\\s*<meta[^>]*(?:property|name)=["']${key.replace(/:/g, ':')}["'][^>]*>`,
      'gi',
    )
    out = out.replace(re, '')
  }
  out = out.replace(/\s*<link[^>]*rel=["']canonical["'][^>]*>/gi, '')
  out = out.replace(/\s*<title>[\s\S]*?<\/title>/i, '')
  return out
}

export function injectAthleteMeta(html: string, meta: AthleteMeta): string {
  const title = meta.titleOverride ?? `${meta.name} — CPU Powerlifting Analytics`
  const description =
    meta.summary && meta.summary.trim()
      ? meta.summary.trim()
      : `Meet history, progression, and qualifying-total standing for ${meta.name}.`

  const tags = [
    `<link rel="canonical" href="${escapeAttr(meta.url)}" />`,
    `<meta property="og:title" content="${escapeAttr(title)}" />`,
    `<meta property="og:description" content="${escapeAttr(description)}" />`,
    `<meta property="og:url" content="${escapeAttr(meta.url)}" />`,
    `<meta property="og:image" content="${escapeAttr(meta.image)}" />`,
    `<meta property="og:image:alt" content="${escapeAttr(meta.imageAltOverride ?? `${meta.name} lifting summary card`)}" />`,
    `<meta name="twitter:title" content="${escapeAttr(title)}" />`,
    `<meta name="twitter:description" content="${escapeAttr(description)}" />`,
    `<meta name="twitter:image" content="${escapeAttr(meta.image)}" />`,
    `<title>${escapeAttr(title)}</title>`,
  ].join('\n    ')

  const stripped = stripOwnedTags(html)
  if (!/<\/head>/i.test(stripped)) return stripped
  return stripped.replace(/<\/head>/i, `  ${tags}\n  </head>`)
}

export interface MeetMeta {
  name: string
  date: string
  image: string
  url: string
  summary?: string | null
}

/** Meet-page variant of the same replace-don't-append transform. */
export function injectMeetMeta(html: string, meta: MeetMeta): string {
  const title = `${meta.name} (${meta.date}) — CPU Powerlifting Analytics`
  const description =
    meta.summary && meta.summary.trim()
      ? meta.summary.trim()
      : `Canadian results from ${meta.name} on ${meta.date}.`
  return injectAthleteMeta(html, {
    name: meta.name,
    image: meta.image,
    url: meta.url,
    summary: description,
    titleOverride: title,
    imageAltOverride: `${meta.name} results summary card`,
  })
}

/** One-line stat summary for the card + description, from the history payload. */
export function summarize(
  d: {
    found?: boolean
    sex?: string | null
    latest_weight_class?: string | null
    best_total_kg?: number | null
    meet_count?: number | null
  } | null,
): string | null {
  if (!d || !d.found) return null
  const bits: string[] = []
  if (d.best_total_kg != null) bits.push(`${d.best_total_kg} kg best total`)
  if (d.latest_weight_class) bits.push(`${d.latest_weight_class} kg class`)
  if (d.meet_count != null) {
    bits.push(`${d.meet_count} meet${d.meet_count === 1 ? '' : 's'}`)
  }
  return bits.length ? bits.join(' · ') : null
}
