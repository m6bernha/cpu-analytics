// Meet prestige resolution. Reads `frontend/src/data/meet_prestige_catalogue.json`
// (Vite static import, mirrors the About-tab pattern) and returns the
// highest-weight tier match for a given meet. Non-Canada meets auto-elevate
// to `international` regardless of the catalogue.
//
// Catalogue entries are case-insensitive substring/anchor regex patterns.
// Highest weight wins on multi-match. No match falls back to `local` with
// weight 0.
//
// See ADR 0001 (docs/adr/0001-athlete-cards-design.md) for the design.

import catalogueRaw from '../data/meet_prestige_catalogue.json'
import { TIER_TOKENS, type Tier } from './colors'

interface CataloguePattern {
  pattern: string
  tier: Tier
  weight: number
}

const COMPILED_PATTERNS: ReadonlyArray<{
  regex: RegExp
  tier: Tier
  weight: number
}> = (catalogueRaw as CataloguePattern[]).map((entry) => ({
  regex: new RegExp(entry.pattern, 'i'),
  tier: entry.tier,
  weight: entry.weight,
}))

export interface MeetTierResult {
  tier: Tier
  label: string
  weight: number
}

const LOCAL_FALLBACK: MeetTierResult = {
  tier: 'local',
  label: TIER_TOKENS.local.label,
  weight: 0,
}

// Sentinel weight ensures international elevation always beats any catalogue
// match. The number is arbitrary but must exceed every weight in the JSON.
const INTERNATIONAL_WEIGHT = 1000

const INTERNATIONAL: MeetTierResult = {
  tier: 'international',
  label: TIER_TOKENS.international.label,
  weight: INTERNATIONAL_WEIGHT,
}

export interface MeetInput {
  meetName: string | null | undefined
  meetCountry: string | null | undefined
}

export function resolveMeetTier(input: MeetInput): MeetTierResult {
  if (input.meetCountry && input.meetCountry !== 'Canada') {
    return INTERNATIONAL
  }
  const name = input.meetName?.trim()
  if (!name) {
    return LOCAL_FALLBACK
  }
  let best: MeetTierResult = LOCAL_FALLBACK
  for (const entry of COMPILED_PATTERNS) {
    if (entry.regex.test(name) && entry.weight > best.weight) {
      best = {
        tier: entry.tier,
        label: TIER_TOKENS[entry.tier].label,
        weight: entry.weight,
      }
    }
  }
  return best
}

export function resolveHighestTier(meets: ReadonlyArray<MeetInput>): MeetTierResult {
  let best: MeetTierResult = LOCAL_FALLBACK
  for (const meet of meets) {
    const result = resolveMeetTier(meet)
    if (result.weight > best.weight) {
      best = result
    }
  }
  return best
}
