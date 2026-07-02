// localStorage-backed "My lifters" pin list.
//
// No backend, no accounts: pins live in this browser only. The hook uses
// useSyncExternalStore so every component reading pins re-renders when
// any component writes, and the 'storage' listener keeps multiple open
// tabs in sync.

import { useCallback, useSyncExternalStore } from 'react'

const STORAGE_KEY = 'cpu-pinned-lifters'
const CHANGE_EVENT = 'cpu-pinned-lifters-changed'
const MAX_PINS = 12

function read(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr: unknown = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr.filter((x): x is string => typeof x === 'string')
  } catch {
    return []
  }
}

let snapshot: string[] = read()

function subscribe(onChange: () => void): () => void {
  const handler = () => {
    snapshot = read()
    onChange()
  }
  window.addEventListener(CHANGE_EVENT, handler)
  window.addEventListener('storage', handler)
  return () => {
    window.removeEventListener(CHANGE_EVENT, handler)
    window.removeEventListener('storage', handler)
  }
}

function getSnapshot(): string[] {
  return snapshot
}

function write(names: string[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(names))
  } catch {
    // Storage unavailable: keep the in-memory list for this session.
  }
  snapshot = names
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function usePinnedLifters(): {
  pinned: string[]
  isPinned: (name: string) => boolean
  togglePin: (name: string) => void
} {
  const pinned = useSyncExternalStore(subscribe, getSnapshot)

  const isPinned = useCallback(
    (name: string) => pinned.includes(name),
    [pinned],
  )

  const togglePin = useCallback((name: string) => {
    const current = getSnapshot()
    if (current.includes(name)) {
      write(current.filter((n) => n !== name))
    } else {
      // Newest-first, capped so the chip row stays scannable.
      write([name, ...current].slice(0, MAX_PINS))
    }
  }, [])

  return { pinned, isPinned, togglePin }
}
