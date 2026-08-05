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

export function athletePath(name: string): string {
  return `/athlete/${encodeURIComponent(name)}`
}

export function parseRoute(pathname: string = window.location.pathname): Route {
  const m = pathname.match(/^\/athlete\/(.+?)\/?$/)
  if (!m) return { kind: 'app' }
  let name: string
  try {
    name = decodeURIComponent(m[1])
  } catch {
    // Malformed percent-encoding: treat as a non-route rather than throwing
    // during render.
    return { kind: 'app' }
  }
  name = name.trim()
  if (!name) return { kind: 'app' }
  return { kind: 'athlete', name }
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
