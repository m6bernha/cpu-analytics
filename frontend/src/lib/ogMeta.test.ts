import { describe, expect, it } from 'vitest'

import { injectAthleteMeta, summarize } from './ogMeta'

// Mirrors the real index.html head: site-wide og/twitter tags already
// present, which the injector must REPLACE rather than duplicate.
const HTML = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="description" content="site description" />
    <link rel="canonical" href="https://cpu-analytics.vercel.app/" />
    <meta property="og:title" content="CPU Powerlifting Analytics" />
    <meta property="og:description" content="site og description" />
    <meta property="og:type" content="website" />
    <meta property="og:url" content="https://cpu-analytics.vercel.app/" />
    <meta property="og:image" content="https://cpu-analytics.vercel.app/og-image.png" />
    <meta property="og:image:width" content="1200" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="CPU Powerlifting Analytics" />
    <meta name="twitter:image" content="https://cpu-analytics.vercel.app/og-image.png" />
    <title>CPU Powerlifting Analytics</title>
  </head>
  <body><div id="root"></div></body>
</html>`

const META = {
  name: 'Bob B',
  image: 'https://x.test/api/og/athlete?name=Bob%20B',
  url: 'https://x.test/athlete/Bob%20B',
}

const count = (s: string, re: RegExp) => (s.match(re) ?? []).length

describe('injectAthleteMeta', () => {
  it('emits exactly one of each owned tag', () => {
    const out = injectAthleteMeta(HTML, META)
    expect(count(out, /property="og:title"/g)).toBe(1)
    expect(count(out, /property="og:description"/g)).toBe(1)
    expect(count(out, /property="og:image"/g)).toBe(1)
    expect(count(out, /property="og:url"/g)).toBe(1)
    expect(count(out, /name="twitter:title"/g)).toBe(1)
    expect(count(out, /name="twitter:image"/g)).toBe(1)
    expect(count(out, /<title>/g)).toBe(1)
    expect(count(out, /rel="canonical"/g)).toBe(1)
  })

  it('replaces the site-wide values with athlete-specific ones', () => {
    const out = injectAthleteMeta(HTML, META)
    expect(out).toContain('<title>Bob B — CPU Powerlifting Analytics</title>')
    expect(out).toContain(`content="${META.image}"`)
    expect(out).toContain(`href="${META.url}"`)
    expect(out).not.toContain('og-image.png')
    expect(out).not.toMatch(/og:title" content="CPU Powerlifting Analytics"/)
  })

  it('leaves tags it does not own alone', () => {
    const out = injectAthleteMeta(HTML, META)
    expect(out).toContain('<meta charset="UTF-8" />')
    expect(out).toContain('rel="icon"')
    expect(out).toContain('property="og:type"')
    expect(out).toContain('name="twitter:card"')
    expect(out).toContain('property="og:image:width"')
    expect(out).toContain('<div id="root"></div>')
  })

  it('uses the stat summary as the description when present', () => {
    const out = injectAthleteMeta(HTML, { ...META, summary: '565 kg best total · 83 kg class' })
    expect(out).toContain('565 kg best total · 83 kg class')
  })

  it('falls back to a generic description without a summary', () => {
    const out = injectAthleteMeta(HTML, META)
    expect(out).toContain('Meet history, progression, and qualifying-total standing for Bob B.')
  })

  it('escapes quotes and angle brackets so a name cannot break out of the attribute', () => {
    const out = injectAthleteMeta(HTML, {
      ...META,
      name: 'Evil" onload="alert(1)',
    })
    expect(out).not.toContain('onload="alert(1)"')
    expect(out).toContain('&quot;')
  })

  it('escapes ampersands in names', () => {
    const out = injectAthleteMeta(HTML, { ...META, name: 'A & B' })
    expect(out).toContain('A &amp; B')
  })

  it('returns the input unchanged when there is no head to inject into', () => {
    expect(injectAthleteMeta('<p>no head</p>', META)).toBe('<p>no head</p>')
  })
})

describe('summarize', () => {
  it('builds a stat line from the history payload', () => {
    expect(
      summarize({ found: true, best_total_kg: 565, latest_weight_class: '83', meet_count: 4 }),
    ).toBe('565 kg best total · 83 kg class · 4 meets')
  })

  it('singularizes a single meet', () => {
    expect(summarize({ found: true, meet_count: 1 })).toBe('1 meet')
  })

  it('returns null for unknown or not-found lifters', () => {
    expect(summarize(null)).toBeNull()
    expect(summarize({ found: false, best_total_kg: 500 })).toBeNull()
    expect(summarize({ found: true })).toBeNull()
  })
})
