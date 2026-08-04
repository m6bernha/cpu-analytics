// Pure helpers for the Scout form (roster parsing + manual overrides).
// Kept out of Scout.tsx so the logic is unit-testable without rendering
// the tab.

import type { ScoutManualOverride, ScoutRosterEntry } from './api'

// One name per line; `@` prefix tags a homie. Internal whitespace is
// collapsed because the backend matches names exactly (case-insensitive)
// and a pasted double space would silently unrank the lifter (found in
// the 2026-08-04 accuracy pass).
export function parseRoster(text: string): ScoutRosterEntry[] {
  const entries: ScoutRosterEntry[] = []
  const seen = new Set<string>()
  for (const raw of text.split('\n')) {
    let line = raw.replace(/\s+/g, ' ').trim()
    if (!line) continue
    const isHomie = line.startsWith('@')
    if (isHomie) line = line.slice(1).trim()
    if (!line) continue
    const key = line.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    entries.push({ name: line, is_homie: isHomie })
  }
  return entries
}

export interface OverrideDraft {
  name: string
  bestTotal: string
  squat: string
  bench: string
  deadlift: string
  weightClass: string
  sex: '' | 'F' | 'M'
  lastMeetDate: string
}

export const EMPTY_OVERRIDE: OverrideDraft = {
  name: '',
  bestTotal: '',
  squat: '',
  bench: '',
  deadlift: '',
  weightClass: '',
  sex: '',
  lastMeetDate: '',
}

function parseKg(s: string): number | null {
  const v = Number(s)
  return s.trim() !== '' && Number.isFinite(v) && v > 0 ? v : null
}

// A draft only counts once it has a name and a positive best total (the
// backend requires best_total_kg; it stands in as the projection).
export function draftToApi(d: OverrideDraft): ScoutManualOverride | null {
  const total = parseKg(d.bestTotal)
  if (!d.name.trim() || total === null) return null
  return {
    best_total_kg: total,
    squat_best_kg: parseKg(d.squat),
    bench_best_kg: parseKg(d.bench),
    deadlift_best_kg: parseKg(d.deadlift),
    weight_class: d.weightClass.trim() || null,
    sex: d.sex || null,
    last_meet_date: /^\d{4}-\d{2}-\d{2}$/.test(d.lastMeetDate)
      ? d.lastMeetDate
      : null,
  }
}

// Merge override drafts into the parsed roster. Overrides attach to the
// matching roster line (case-insensitive); complete drafts whose name has
// no roster line are appended as their own entries so "add a lifter
// OpenIPF does not know" works without editing the textarea.
export function buildRosterEntries(
  roster: ScoutRosterEntry[],
  overrides: OverrideDraft[],
): ScoutRosterEntry[] {
  const overrideMap = new Map<string, ScoutManualOverride>()
  for (const d of overrides) {
    const api = draftToApi(d)
    if (api) overrideMap.set(d.name.trim().toLowerCase(), api)
  }
  const entries: ScoutRosterEntry[] = roster.map((e) => {
    const o = overrideMap.get(e.name.toLowerCase())
    return o ? { ...e, manual_override: o } : e
  })
  const rosterNames = new Set(roster.map((e) => e.name.toLowerCase()))
  for (const d of overrides) {
    const key = d.name.trim().toLowerCase()
    const api = overrideMap.get(key)
    if (api && !rosterNames.has(key)) {
      entries.push({ name: d.name.trim(), is_homie: false, manual_override: api })
      rosterNames.add(key)
    }
  }
  return entries
}
