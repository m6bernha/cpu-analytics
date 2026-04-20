// Regression tests for the useUrlState collision guard.
//
// The guard warns in dev when two components register the same URL key.
// It uses ref-counting so React.StrictMode double-mount does not false-positive.

import { StrictMode } from 'react'
import { render, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useUrlState } from './useUrlState'

// Minimal component that registers URL keys via useUrlState.
function KeyHolder({ keys }: { keys: Record<string, string> }) {
  useUrlState(keys)
  return null
}

describe('useUrlState collision guard', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    warnSpy.mockRestore()
  })

  it('warns when two components register an overlapping key', () => {
    const { unmount: u1 } = render(<KeyHolder keys={{ tab: 'progression' }} />)
    const { unmount: u2 } = render(<KeyHolder keys={{ tab: 'progression' }} />)

    const calls = warnSpy.mock.calls.map((c: unknown[]) => c.join(' '))
    const fired = calls.some((msg: string) => msg.includes('[useUrlState] key "tab"'))
    expect(fired).toBe(true)

    u1()
    u2()
  })

  it('does not warn when two components register disjoint keys', () => {
    const { unmount: u1 } = render(<KeyHolder keys={{ tab: 'progression' }} />)
    const { unmount: u2 } = render(<KeyHolder keys={{ mode: 'search' }} />)

    const calls = warnSpy.mock.calls.map((c: unknown[]) => c.join(' '))
    const fired = calls.some((msg: string) => msg.includes('[useUrlState]'))
    expect(fired).toBe(false)

    u1()
    u2()
  })

  it('does not warn for disjoint keys inside React.StrictMode', () => {
    const { unmount } = render(
      <StrictMode>
        <KeyHolder keys={{ tab: 'progression' }} />
        <KeyHolder keys={{ mode: 'search' }} />
      </StrictMode>,
    )

    act(() => {})

    const calls = warnSpy.mock.calls.map((c: unknown[]) => c.join(' '))
    const fired = calls.some((msg: string) => msg.includes('[useUrlState]'))
    expect(fired).toBe(false)

    unmount()
  })
})
