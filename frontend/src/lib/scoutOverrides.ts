// Pure helpers for the Scout form (roster parsing + manual overrides).
// Kept out of Scout.tsx so the logic is unit-testable without rendering
// the tab.

import type { ScoutManualOverride, ScoutRosterEntry } from './api'

// Roster parsing.
//
// Entry lists do not arrive as one bare name per line. They arrive as a
// spreadsheet copy-paste with weight class and division columns, as a
// "Last, First" export, as a numbered list, or as text dragged out of a
// PDF. The Sunny Daze 2026 roster had to be reconstructed by hand from a
// PDF for exactly this reason, so the parser now recognises those shapes.
//
// Internal whitespace is always collapsed because the backend matches
// names exactly (case-insensitive), and a pasted double space would
// silently unrank the lifter (found in the 2026-08-04 accuracy pass).

export type RosterFormat = 'lines' | 'tab' | 'comma' | 'last-first'

export interface RosterParseResult {
  entries: ScoutRosterEntry[]
  /** Which shape the input was read as. Surfaced so a wrong guess is visible. */
  format: RosterFormat
  /** A leading column-header row was recognised and dropped. */
  droppedHeader: boolean
  /** Repeat names collapsed into the first occurrence. */
  duplicates: number
  /** Columns present in the input that were not the name column. */
  discardedColumns: number
}

const HEADER_WORDS = new Set([
  'name', 'names', 'lifter', 'lifters', 'athlete', 'athletes', 'competitor',
  'first', 'firstname', 'last', 'lastname', 'fullname', 'weight', 'class',
  'weightclass', 'division', 'div', 'team', 'club', 'age', 'sex', 'gender',
  'total', 'entry', 'place', 'lot', 'lotnumber', 'bodyweight', 'bw', 'flight',
  'session', 'platform', 'federation', 'member', 'id', 'email', 'country',
  'state', 'province',
])

// Values that are never a given name, used to stop a "Name, Division" or
// "Name, Sex" list being mistaken for "Last, First".
const NON_NAME_TOKENS = new Set([
  'open', 'junior', 'juniors', 'subjunior', 'subjuniors', 'master', 'masters',
  'm1', 'm2', 'm3', 'm4', 'teen', 'teenage', 'youth', 'novice', 'guest',
  'raw', 'equipped', 'classic', 'male', 'female', 'men', 'women', 'mens',
  'womens', 'm', 'f', 'sbd', 'bench', 'squat', 'deadlift', 'na', 'none',
])

/** Two or more words, letters only (plus apostrophes, hyphens, periods). */
const FULL_NAME = /^\p{L}[\p{L}'’.-]*(?:\s+\p{L}[\p{L}'’.-]*)+$/u
/** One or more words, letters only. Used for the "Last, First" test. */
const NAME_TOKENS = /^\p{L}[\p{L}'’.-]*(?:\s+\p{L}[\p{L}'’.-]*)*$/u

function normalizeHeaderWord(value: string): string {
  return value.toLowerCase().replace(/[^a-z]/g, '')
}

function looksLikeHeaderRow(fields: string[]): boolean {
  const words = fields.map(normalizeHeaderWord).filter(Boolean)
  if (!words.length) return false
  return words.every((w) => HEADER_WORDS.has(w))
}

/**
 * Strip a trailing weight class from a bare line: "Jane Doe 83",
 * "Jane Doe 83kg", "Jane Doe 120+".
 *
 * Deliberately requires the trailing token to be a bare number, optionally
 * with `kg` or a `+`. OpenIPF disambiguates duplicate names with a `#`
 * suffix ("Anthony Wong #2") and that must survive untouched, because it
 * is part of the name the backend matches on.
 */
function stripTrailingWeightClass(line: string): string {
  const stripped = line.replace(/\s+\d{2,3}(?:\.\d+)?\s*(?:kg)?\+?$/i, '')
  // Never strip away the whole line, and never leave a single token where
  // the input clearly held a full name.
  return stripped.trim() ? stripped.trim() : line
}

function cleanCell(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/** Score a column by how many of its values look like a person's full name. */
function nameColumnScore(values: string[]): number {
  if (!values.length) return 0
  const hits = values.filter((v) => FULL_NAME.test(v)).length
  return hits / values.length
}

export function parseRosterDetailed(text: string): RosterParseResult {
  const rawLines = text.split('\n').map((l) => l.replace(/\r$/, ''))
  const nonEmpty = rawLines.filter((l) => l.trim())

  let format: RosterFormat = 'lines'
  let droppedHeader = false
  let discardedColumns = 0
  let names: { name: string; isHomie: boolean }[] = []

  const hasTabs = nonEmpty.some((l) => l.includes('\t'))
  const commaLines = nonEmpty.filter((l) => l.includes(',')).length
  // A majority rule rather than "any", so one lifter with a comma in their
  // name does not flip a plain list into column mode.
  const mostlyCommas = nonEmpty.length > 0 && commaLines / nonEmpty.length >= 0.6

  if (hasTabs || mostlyCommas) {
    const delimiter = hasTabs ? '\t' : ','
    format = hasTabs ? 'tab' : 'comma'

    let rows = nonEmpty.map((l) => l.split(delimiter).map(cleanCell))

    if (rows.length > 1 && looksLikeHeaderRow(rows[0])) {
      rows = rows.slice(1)
      droppedHeader = true
    }

    // "Last, First" is comma-separated too, and naive splitting turns it
    // into two columns of names. Telling the two apart matters because the
    // failure is silent and ugly: "Jane Doe, Open" would come back as
    // "Open Jane Doe", and "Jane Doe, Vireo Powerlifting" as "Vireo
    // Powerlifting Jane Doe".
    //
    // The discriminator is the FIRST field. A surname is one token; a full
    // name in a name-plus-something list is two or more. Requiring most
    // rows to have a single-token first field separates them, and the
    // second field additionally may not be a division or sex value.
    const twoFieldRows = rows.filter((r) => r.length === 2)
    const lastFirstRows = twoFieldRows.filter((r) => {
      const first = r[0].replace(/^@/, '').trim()
      const second = r[1].trim()
      return (
        NAME_TOKENS.test(first) &&
        NAME_TOKENS.test(second) &&
        first.split(' ').length === 1 &&
        second.split(' ').length <= 3 &&
        !NON_NAME_TOKENS.has(normalizeHeaderWord(second))
      )
    })
    const isLastFirst =
      delimiter === ',' &&
      twoFieldRows.length === rows.length &&
      rows.length > 0 &&
      lastFirstRows.length / rows.length >= 0.8

    if (isLastFirst) {
      format = 'last-first'
      names = rows.map((r) => {
        const isHomie = r[0].startsWith('@')
        const last = (isHomie ? r[0].slice(1) : r[0]).trim()
        return { name: cleanCell(`${r[1]} ${last}`), isHomie }
      })
    } else {
      const width = Math.max(...rows.map((r) => r.length))
      let bestCol = 0
      let bestScore = -1
      for (let c = 0; c < width; c++) {
        const score = nameColumnScore(
          rows.map((r) => (r[c] ?? '').replace(/^@/, '').trim()).filter(Boolean),
        )
        if (score > bestScore) {
          bestScore = score
          bestCol = c
        }
      }
      discardedColumns = Math.max(0, width - 1)
      names = rows
        .map((r) => {
          const cell = (r[bestCol] ?? '').trim()
          const isHomie = cell.startsWith('@') || (r[0] ?? '').startsWith('@')
          return { name: cleanCell(cell.replace(/^@/, '')), isHomie }
        })
        .filter((n) => n.name)
    }
  } else {
    names = nonEmpty
      .map((raw) => {
        // List markers and bullets only get stripped here, never in column
        // mode, where a leading number is a legitimate field of its own.
        let line = cleanCell(raw)
          .replace(/^[-•*·]\s+/, '')
          .replace(/^\d{1,3}[.)\]]\s+/, '')
        const isHomie = line.startsWith('@')
        if (isHomie) line = line.slice(1).trim()
        line = stripTrailingWeightClass(line)
        return { name: line, isHomie }
      })
      .filter((n) => n.name)

    if (names.length > 1 && looksLikeHeaderRow([names[0].name])) {
      names = names.slice(1)
      droppedHeader = true
    }
  }

  // Dedupe, case-insensitive, first occurrence wins. Homie-ness is a union:
  // tagging any one occurrence tags the lifter.
  const entries: ScoutRosterEntry[] = []
  const index = new Map<string, number>()
  let duplicates = 0
  for (const { name, isHomie } of names) {
    if (!name) continue
    const key = name.toLowerCase()
    const at = index.get(key)
    if (at !== undefined) {
      duplicates += 1
      if (isHomie) entries[at].is_homie = true
      continue
    }
    index.set(key, entries.length)
    entries.push({ name, is_homie: isHomie })
  }

  return { entries, format, droppedHeader, duplicates, discardedColumns }
}

export function parseRoster(text: string): ScoutRosterEntry[] {
  return parseRosterDetailed(text).entries
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
