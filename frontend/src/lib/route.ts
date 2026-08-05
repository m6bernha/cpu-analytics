// Minimal path routing, in the same spirit as useUrlState (which owns the
// QUERY STRING). This module owns the PATHNAME. The two compose because
// useUrlState's writeUrl() preserves window.location.pathname verbatim and
// this module never touches search params it does not own.
//
// Phase 1a of the social layer (docs/adr/0002-social-layer-stateless.md).
// Deliberately hand-rolled rather than adding react-router: the app has
// exactly one dynamic route.
//
// Slug format is the URL-encoded EXACT OpenIPF name. Pretty hyphenated
// slugs would collide with genuinely hyphenated names (and OpenIPF keys on
// the exact string), so the round-trip has to be lossless.

import { useEffect, useState } from 'react'

export const ROUTE_EVENT = 'cpu-analytics:routechange'

export type Route =
  | { kind: 'app' }
  | { kind: 'athlete'; name: string }
  | { kind: 'meet'; name: string; date: string }

export function athletePath(name: string): string {
  return `/athlete/${encodeURIComponent(name)}`
}

/** A meet is keyed by (name, date); the date disambiguates recurring names. */
export function meetPath(name: string, date: string): string {
  return `/meet/${encodeURIComponent(name)}/${date}`
}

function decodeSegment(raw: string): string | null {
  try {
    const s = decodeURIComponent(raw).trim()
    return s || null
  } catch {
    // Malformed percent-encoding: treat as a non-route rather than
    // throwing during render.
    return null
  }
}

export function parseRoute(pathname: string = window.location.pathname): Route {
  // Meet first: its name segment can itself contain slashes only when
  // encoded, so the date anchor keeps this unambiguous.
  const meet = pathname.match(/^\/meet\/(.+)\/(\d{4}-\d{2}-\d{2})\/?$/)
  if (meet) {
    const name = decodeSegment(meet[1])
    return name ? { kind: 'meet', name, date: meet[2] } : { kind: 'app' }
  }

  const athlete = pathname.match(/^\/athlete\/(.+?)\/?$/)
  if (athlete) {
    const name = decodeSegment(athlete[1])
    return name ? { kind: 'athlete', name } : { kind: 'app' }
  }

  return { kind: 'app' }
}

function announce() {
  window.dispatchEvent(new Event(ROUTE_EVENT))
  // useUrlState listens on popstate; a synthetic one keeps every mounted
  // instance's query-string state in sync after a path change.
  window.dispatchEvent(new Event('popstate'))
}

/** Push a new path, preserving nothing from the current query by default. */
export function navigate(path: string): void {
  if (path === window.location.pathname + window.location.search) return
  window.history.pushState(null, '', path)
  announce()
}

/**
 * Rewrite a legacy `?tab=lookup&lifter=X` deep link to `/athlete/X`.
 *
 * Only single-lifter search links redirect. Compare links
 * (`mode=compare&lifters=A,B`) and the bare lookup tab are left alone —
 * they are workspace views, not per-athlete pages. Unrelated params
 * (era, view_mode) ride along so a shared link keeps its display state.
 *
 * Uses replaceState so the legacy URL does not linger in history and the
 * back button still leaves the site cleanly.
 *
 * @returns true if a redirect happened.
 */
export function redirectLegacyLifterUrl(): boolean {
  if (window.location.pathname !== '/') return false
  const p = new URLSearchParams(window.location.search)
  if (p.get('tab') !== 'lookup') return false
  const mode = p.get('mode')
  if (mode && mode !== 'search') return false
  const lifter = p.get('lifter')
  if (!lifter || !lifter.trim()) return false

  p.delete('tab')
  p.delete('lifter')
  p.delete('mode')
  const qs = p.toString()
  window.history.replaceState(
    null,
    '',
    athletePath(lifter.trim()) + (qs ? `?${qs}` : '') + window.location.hash,
  )
  announce()
  return true
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute())
  useEffect(() => {
    const sync = () => setRoute(parseRoute())
    window.addEventListener('popstate', sync)
    window.addEventListener(ROUTE_EVENT, sync)
    return () => {
      window.removeEventListener('popstate', sync)
      window.removeEventListener(ROUTE_EVENT, sync)
    }
  }, [])
  return route
}
