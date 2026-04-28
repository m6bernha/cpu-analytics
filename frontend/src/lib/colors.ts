// Meet-prestige tier tokens. Locked palette per memory `project_color_tokens`:
// no metallic gradients, only the existing amber + zinc families. Amber is
// reserved for `national` and `international` (the two tiers a viewer should
// notice); regional / provincial / local stay in zinc.
//
// Used by the AthleteCard tier ring + chip styling. Do not introduce
// gold/silver/bronze hex literals -- this file is the only place tier
// styling lives.

export const TIER_TOKENS = {
  international: {
    ring: 'ring-amber-300/70',
    text: 'text-amber-200',
    bg: 'bg-amber-950/30',
    label: 'International',
  },
  national: {
    ring: 'ring-amber-400/70',
    text: 'text-amber-300',
    bg: 'bg-amber-900/20',
    label: 'National',
  },
  regional: {
    ring: 'ring-zinc-300/60',
    text: 'text-zinc-200',
    bg: 'bg-zinc-800/40',
    label: 'Regional',
  },
  provincial: {
    ring: 'ring-zinc-400/40',
    text: 'text-zinc-300',
    bg: 'bg-zinc-800/20',
    label: 'Provincial',
  },
  local: {
    ring: 'ring-zinc-500/30',
    text: 'text-zinc-400',
    bg: 'bg-zinc-900/40',
    label: 'Local',
  },
} as const

export type Tier = keyof typeof TIER_TOKENS
