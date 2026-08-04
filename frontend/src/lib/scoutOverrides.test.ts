import { describe, expect, it } from 'vitest'

import {
  EMPTY_OVERRIDE,
  buildRosterEntries,
  draftToApi,
  parseRoster,
  type OverrideDraft,
} from './scoutOverrides'

const draft = (patch: Partial<OverrideDraft>): OverrideDraft => ({
  ...EMPTY_OVERRIDE,
  ...patch,
})

describe('parseRoster', () => {
  it('parses names, homie prefixes, and dedupes case-insensitively', () => {
    const entries = parseRoster('Jane Doe\n@John Smith\n\njane doe\n')
    expect(entries).toEqual([
      { name: 'Jane Doe', is_homie: false },
      { name: 'John Smith', is_homie: true },
    ])
  })

  it('collapses internal whitespace so backend exact-match still hits', () => {
    const entries = parseRoster('  Jane   Doe \n@  John  Smith')
    expect(entries).toEqual([
      { name: 'Jane Doe', is_homie: false },
      { name: 'John Smith', is_homie: true },
    ])
  })
})

describe('draftToApi', () => {
  it('requires a name and a positive best total', () => {
    expect(draftToApi(draft({ name: '', bestTotal: '600' }))).toBeNull()
    expect(draftToApi(draft({ name: 'A', bestTotal: '' }))).toBeNull()
    expect(draftToApi(draft({ name: 'A', bestTotal: '0' }))).toBeNull()
    expect(draftToApi(draft({ name: 'A', bestTotal: 'abc' }))).toBeNull()
    expect(draftToApi(draft({ name: 'A', bestTotal: '600' }))).not.toBeNull()
  })

  it('maps optional fields, blank to null', () => {
    const api = draftToApi(
      draft({
        name: 'A',
        bestTotal: '600',
        squat: '220',
        weightClass: ' 83 ',
        sex: 'M',
        lastMeetDate: '2026-01-15',
      }),
    )
    expect(api).toEqual({
      best_total_kg: 600,
      squat_best_kg: 220,
      bench_best_kg: null,
      deadlift_best_kg: null,
      weight_class: '83',
      sex: 'M',
      last_meet_date: '2026-01-15',
    })
  })

  it('rejects malformed dates instead of sending them', () => {
    const api = draftToApi(
      draft({ name: 'A', bestTotal: '600', lastMeetDate: '15/01/2026' }),
    )
    expect(api?.last_meet_date).toBeNull()
  })
})

describe('buildRosterEntries', () => {
  it('attaches an override to the matching roster line case-insensitively', () => {
    const entries = buildRosterEntries(
      [{ name: 'Jane Doe', is_homie: true }],
      [draft({ name: 'jane doe', bestTotal: '450' })],
    )
    expect(entries).toHaveLength(1)
    expect(entries[0].is_homie).toBe(true)
    expect(entries[0].manual_override?.best_total_kg).toBe(450)
  })

  it('appends complete overrides whose name has no roster line', () => {
    const entries = buildRosterEntries(
      [{ name: 'Jane Doe', is_homie: false }],
      [draft({ name: 'New Lifter', bestTotal: '500' })],
    )
    expect(entries).toHaveLength(2)
    expect(entries[1].name).toBe('New Lifter')
    expect(entries[1].manual_override?.best_total_kg).toBe(500)
  })

  it('ignores incomplete overrides and leaves the roster untouched', () => {
    const entries = buildRosterEntries(
      [{ name: 'Jane Doe', is_homie: false }],
      [draft({ name: 'Jane Doe', bestTotal: '' }), draft({ name: '', bestTotal: '500' })],
    )
    expect(entries).toHaveLength(1)
    expect(entries[0].manual_override).toBeUndefined()
  })

  it('does not append the same override name twice', () => {
    const entries = buildRosterEntries(
      [],
      [
        draft({ name: 'New Lifter', bestTotal: '500' }),
        draft({ name: 'new lifter', bestTotal: '510' }),
      ],
    )
    expect(entries).toHaveLength(1)
  })
})
