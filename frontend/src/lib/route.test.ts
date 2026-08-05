import { beforeEach, describe, expect, it } from 'vitest'

import { athletePath, meetPath, parseRoute, redirectLegacyLifterUrl } from './route'

function setUrl(url: string) {
  window.history.replaceState(null, '', url)
}

beforeEach(() => setUrl('/'))

describe('athletePath', () => {
  it('percent-encodes so the name round-trips losslessly', () => {
    expect(athletePath('Bob B')).toBe('/athlete/Bob%20B')
    expect(parseRoute(athletePath('Bob B'))).toEqual({
      kind: 'athlete',
      name: 'Bob B',
    })
  })

  it('survives names with hyphens, accents, and slashes', () => {
    for (const name of ['Amélie Picher-Plante', 'A/B Tester', "O'Neill-Smith"]) {
      expect(parseRoute(athletePath(name))).toEqual({ kind: 'athlete', name })
    }
  })
})

describe('parseRoute', () => {
  it('treats non-athlete paths as the app shell', () => {
    expect(parseRoute('/')).toEqual({ kind: 'app' })
    expect(parseRoute('/about')).toEqual({ kind: 'app' })
    expect(parseRoute('/athlete')).toEqual({ kind: 'app' })
    expect(parseRoute('/athlete/')).toEqual({ kind: 'app' })
  })

  it('tolerates a trailing slash on a real athlete path', () => {
    expect(parseRoute('/athlete/Bob%20B/')).toEqual({
      kind: 'athlete',
      name: 'Bob B',
    })
  })

  it('does not throw on malformed percent-encoding', () => {
    expect(parseRoute('/athlete/%E0%A4%A')).toEqual({ kind: 'app' })
  })

  it('treats a whitespace-only name as no route', () => {
    expect(parseRoute('/athlete/%20%20')).toEqual({ kind: 'app' })
  })
})

describe('meet routes', () => {
  it('round-trips a meet name and date', () => {
    expect(meetPath('BC Open', '2025-01-15')).toBe('/meet/BC%20Open/2025-01-15')
    expect(parseRoute('/meet/BC%20Open/2025-01-15')).toEqual({
      kind: 'meet',
      name: 'BC Open',
      date: '2025-01-15',
    })
  })

  it('handles meet names containing slashes and accents', () => {
    for (const name of ['Est/Ouest Championnat', 'Championnat Québécois']) {
      expect(parseRoute(meetPath(name, '2026-03-14'))).toEqual({
        kind: 'meet',
        name,
        date: '2026-03-14',
      })
    }
  })

  it('requires a well-formed trailing date', () => {
    expect(parseRoute('/meet/BC%20Open')).toEqual({ kind: 'app' })
    expect(parseRoute('/meet/BC%20Open/2025-1-5')).toEqual({ kind: 'app' })
    expect(parseRoute('/meet/BC%20Open/not-a-date')).toEqual({ kind: 'app' })
  })

  it('tolerates a trailing slash', () => {
    expect(parseRoute('/meet/BC%20Open/2025-01-15/')).toEqual({
      kind: 'meet',
      name: 'BC Open',
      date: '2025-01-15',
    })
  })

  it('does not confuse an athlete path for a meet path', () => {
    expect(parseRoute('/athlete/Bob%20B')).toEqual({ kind: 'athlete', name: 'Bob B' })
  })
})

describe('redirectLegacyLifterUrl', () => {
  it('rewrites a single-lifter lookup link to the canonical path', () => {
    setUrl('/?tab=lookup&lifter=Bob%20B')
    expect(redirectLegacyLifterUrl()).toBe(true)
    expect(window.location.pathname).toBe('/athlete/Bob%20B')
    expect(window.location.search).toBe('')
  })

  it('carries unrelated display params across the redirect', () => {
    setUrl('/?tab=lookup&lifter=Bob%20B&era=2027&view_mode=per_lift')
    expect(redirectLegacyLifterUrl()).toBe(true)
    expect(window.location.pathname).toBe('/athlete/Bob%20B')
    const p = new URLSearchParams(window.location.search)
    expect(p.get('era')).toBe('2027')
    expect(p.get('view_mode')).toBe('per_lift')
    expect(p.get('tab')).toBeNull()
    expect(p.get('lifter')).toBeNull()
  })

  it('leaves compare links alone — they are a workspace, not a profile', () => {
    setUrl('/?tab=lookup&mode=compare&lifters=Alice%20A,Bob%20B')
    expect(redirectLegacyLifterUrl()).toBe(false)
    expect(window.location.pathname).toBe('/')
  })

  it('leaves other tabs and the bare lookup tab alone', () => {
    for (const url of ['/?tab=lookup', '/?tab=rankings', '/?tab=progression', '/']) {
      setUrl(url)
      expect(redirectLegacyLifterUrl()).toBe(false)
      expect(window.location.pathname).toBe('/')
    }
  })

  it('does not re-fire once already on an athlete path', () => {
    setUrl('/athlete/Bob%20B')
    expect(redirectLegacyLifterUrl()).toBe(false)
  })

  it('ignores an empty lifter param', () => {
    setUrl('/?tab=lookup&lifter=')
    expect(redirectLegacyLifterUrl()).toBe(false)
  })
})
