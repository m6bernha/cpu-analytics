// Minimal URL-backed state hook.
//
// Reads and writes a set of keys on `window.location.search` as a piece of
// component state. Keys whose value equals the default are omitted from the
// URL so a pristine page has a clean URL. Multiple components can use this
// hook at once — each only touches its own keys.
//
// This is a dependency-light alternative to react-router's useSearchParams
// for an app that doesn't have routes, just shareable filter state.

import { useCallback, useEffect, useState } from 'react'

const URL_EVENT = 'cpu-analytics:urlstatechange'

function readParams(): URLSearchParams {
  return new URLSearchParams(window.location.search)
}

function writeUrl(params: URLSearchParams) {
  const qs = params.toString()
  const newUrl =
    `${window.location.pathname}${qs ? '?' + qs : ''}${window.location.hash}`
  window.history.replaceState(null, '', newUrl)
  // Notify other useUrlState instances in the same tab.
  window.dispatchEvent(new Event(URL_EVENT))
}

// Invariant: each useUrlState instance owns a DISJOINT set of URL keys.
// Multiple components sharing the same URL key will stomp on each other
// because each only writes its own keys but reads all of them via the
// URL_EVENT sync. This registry catches collisions in dev.
// Uses a ref-counted Map so StrictMode double-mount doesn't false-positive.
const _registeredKeys = new Map<string, number>()

export function useUrlState<T extends Record<string, string>>(
  defaults: T,
): [T, (patch: Partial<T>) => void] {
  const keys = Object.keys(defaults) as (keyof T)[]

  // Collision check with ref-counting + unmount cleanup.
  useEffect(() => {
    if (!import.meta.env?.DEV) return
    for (const k of keys) {
      const kStr = k as string
      const prev = _registeredKeys.get(kStr) ?? 0
      if (prev >= 1) {
        // eslint-disable-next-line no-console
        console.warn(
          `[useUrlState] key "${kStr}" is registered by more than one component. ` +
          `Instances will stomp each other's URL state.`,
        )
      }
      _registeredKeys.set(kStr, prev + 1)
    }
    return () => {
      for (const k of keys) {
        const kStr = k as string
        const curr = _registeredKeys.get(kStr) ?? 0
        if (curr <= 1) _registeredKeys.delete(kStr)
        else _registeredKeys.set(kStr, curr - 1)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const read = useCallback((): T => {
    const params = readParams()
    const result = { ...defaults }
    for (const k of keys) {
      const raw = params.get(k as string)
      if (raw != null) (result as Record<string, string>)[k as string] = raw
    }
    return result
    // defaults is treated as stable by caller convention; keys is derived from it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const [state, setState] = useState<T>(read)

  useEffect(() => {
    const sync = () => setState(read())
    window.addEventListener('popstate', sync)
    window.addEventListener(URL_EVENT, sync)
    return () => {
      window.removeEventListener('popstate', sync)
      window.removeEventListener(URL_EVENT, sync)
    }
  }, [read])

  const update = useCallback(
    (patch: Partial<T>) => {
      setState((prev) => {
        const next = { ...prev, ...patch } as T
        const params = readParams()
        for (const k of keys) {
          const v = (next as Record<string, string>)[k as string]
          if (v === (defaults as Record<string, string>)[k as string]) {
            params.delete(k as string)
          } else {
            params.set(k as string, String(v))
          }
        }
        writeUrl(params)
        return next
      })
      // defaults/keys treated as stable by convention.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [],
  )

  return [state, update]
}
