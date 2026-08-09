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
  /**
   * schema.org object to emit as JSON-LD. Defaults to a ProfilePage
   * wrapping a Person; injectMeetMeta passes a SportsEvent instead.
   */
  structuredData?: Record<string, unknown>
}

// Tags this module owns end-to-end. Anything not listed here (charset,
// viewport, favicon, og:type, twitter:card) is left untouched.
//
// `description` is in this list and that is the whole point of it being
// here: og:description drives the SOCIAL preview, but the plain
// `<meta name="description">` is what a search engine shows as the result
// snippet. Without owning it, every one of the ~23k athlete and meet pages
// inherited index.html's single site-wide sentence, so they would all have
// competed for the same snippet in search results.
const OWNED_META = [
  'description',
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
  // Same replace-don't-append rule as the meta tags: two ld+json blocks
  // describing the same page is an ambiguity we control, so remove any
  // before emitting ours.
  out = out.replace(
    /\s*<script[^>]*type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>/gi,
    '',
  )
  return out
}

/**
 * Serialize JSON-LD for embedding in an HTML <script> block.
 *
 * `<` is escaped to < so a value containing "</script>" cannot close
 * the block early and turn data into markup. That is valid JSON and valid
 * JSON-LD, and parsers unescape it transparently. Meet names come from
 * federation-entered free text, so this is a real input, not a hypothetical.
 */
function serializeJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, '\\u003c')
}

export function injectAthleteMeta(html: string, meta: AthleteMeta): string {
  const title = meta.titleOverride ?? `${meta.name} — CPU Powerlifting Analytics`
  const description =
    meta.summary && meta.summary.trim()
      ? meta.summary.trim()
      : `Meet history, progression, and qualifying-total standing for ${meta.name}.`

  // Only claims what the dataset actually knows: who, where the page is,
  // and the public-record summary. No awards, ratings, or affiliations are
  // asserted, because inventing them would be both wrong and a structured-
  // data policy violation.
  const structuredData = meta.structuredData ?? {
    '@context': 'https://schema.org',
    '@type': 'ProfilePage',
    mainEntity: {
      '@type': 'Person',
      name: meta.name,
      url: meta.url,
      description,
    },
  }

  const tags = [
    `<link rel="canonical" href="${escapeAttr(meta.url)}" />`,
    `<meta name="description" content="${escapeAttr(description)}" />`,
    `<meta property="og:title" content="${escapeAttr(title)}" />`,
    `<meta property="og:description" content="${escapeAttr(description)}" />`,
    `<meta property="og:url" content="${escapeAttr(meta.url)}" />`,
    `<meta property="og:image" content="${escapeAttr(meta.image)}" />`,
    `<meta property="og:image:alt" content="${escapeAttr(meta.imageAltOverride ?? `${meta.name} lifting summary card`)}" />`,
    `<meta name="twitter:title" content="${escapeAttr(title)}" />`,
    `<meta name="twitter:description" content="${escapeAttr(description)}" />`,
    `<meta name="twitter:image" content="${escapeAttr(meta.image)}" />`,
    `<title>${escapeAttr(title)}</title>`,
    `<script type="application/ld+json">${serializeJsonLd(structuredData)}</script>`,
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
    structuredData: {
      '@context': 'https://schema.org',
      '@type': 'SportsEvent',
      name: meta.name,
      startDate: meta.date,
      url: meta.url,
      sport: 'Powerlifting',
      description,
      // No `location`: preprocess drops MeetTown/MeetState, so the town is
      // genuinely unknown here. Google needs location for Event rich
      // results, so this markup aids understanding without earning a rich
      // result -- which is the correct trade against inventing a venue.
      // No `eventStatus` either: these are completed meets, and asserting
      // EventScheduled on a past event would be false.
    },
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
