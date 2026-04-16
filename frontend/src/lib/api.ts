// Typed fetch helpers for the backend API.
//
// API_BASE reads from Vite env var first, falls back to localhost for dev.
// In production (Vercel), set VITE_API_BASE to the Fly.io backend URL.

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000'

// ---------- Response types ----------

export type FiltersResponse = {
  sex: string[]
  equipment: string[]
  tested: string[]
  event: string[]
  federation: string[]
  country: string[]
  division: string[]
  weight_class: { M: string[]; F: string[] }
  age_category: string[]
  x_axis: string[]
}

export type ProgressionPoint = {
  x: number
  y: number
  std: number
  lifter_count: number
}

export type ProgressionTrend = {
  slope: number
  intercept: number
  unit: string
  r_squared: number
  residual_std: number
}

export type CohortProjectionPoint = {
  x: number
  y: number
  upper: number
  lower: number
}

export type CohortProjection = {
  points: CohortProjectionPoint[]
  unit: string
}

export type ProgressionResponse = {
  x_label: string
  x_axis: string
  points: ProgressionPoint[]
  trend: ProgressionTrend | null
  projection: CohortProjection | null
  n_lifters: number
  n_meets: number
  n_lifters_before_age_filter: number
  n_all_lifters: number
  avg_first_total: number | null
}

export type LifterSearchResult = {
  Name: string
  Sex: string
  Federation: string
  Country: string
  LatestEquipment: string
  LatestWeightClass: string
  LatestMeetDate: string
  BestTotalKg: number
  MeetCount: number
}

// ---------- Fetchers ----------

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

// Required enum arrays on the filters endpoint. If any of these come back
// empty it's almost certainly a backend init race on a cold Render boot, not
// a real state of the dataset. We throw so TanStack Query retries instead of
// caching the partial response forever.
const REQUIRED_FILTER_ARRAYS: (keyof FiltersResponse)[] = [
  'sex',
  'equipment',
  'event',
  'age_category',
  'x_axis',
]

export async function fetchFilters(): Promise<FiltersResponse> {
  const data = await getJson<FiltersResponse>(`${API_BASE}/api/filters`)
  for (const k of REQUIRED_FILTER_ARRAYS) {
    const v = data[k] as unknown
    if (!Array.isArray(v) || v.length === 0) {
      throw new Error(`Filters response missing or empty: ${k}`)
    }
  }
  return data
}

export type ProgressionQuery = {
  sex?: string
  equipment?: string
  tested?: string
  event?: string
  weight_class?: string
  division?: string
  age_category?: string
  x_axis?: string
  max_gap_months?: string
  same_class_only?: string
}

export function fetchProgression(q: ProgressionQuery): Promise<ProgressionResponse> {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v != null && v !== '') params.set(k, v)
  }
  return getJson<ProgressionResponse>(`${API_BASE}/api/cohort/progression?${params}`)
}

// ---------- Per-lift cohort progression (S/B/D curves) ----------

export type LiftPoint = {
  x: number
  y: number
  lifter_count: number
}

export type LiftProgressionResponse = {
  x_label: string
  lifts: {
    squat: LiftPoint[]
    bench: LiftPoint[]
    deadlift: LiftPoint[]
  }
  n_lifters: number
}

export type LiftProgressionQuery = {
  sex?: string
  equipment?: string
  weight_class?: string
  division?: string
  x_axis?: string
}

export function fetchLiftProgression(
  q: LiftProgressionQuery,
): Promise<LiftProgressionResponse> {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(q)) {
    if (v != null && v !== '') params.set(k, v)
  }
  return getJson<LiftProgressionResponse>(`${API_BASE}/api/cohort/lift_progression?${params}`)
}

export function fetchLifterSearch(
  q: string,
  limit = 25,
): Promise<LifterSearchResult[]> {
  const params = new URLSearchParams({ q, limit: String(limit) })
  return getJson<LifterSearchResult[]>(`${API_BASE}/api/lifters/search?${params}`)
}

// ---------- QT blocks ----------

export type QtBlockRow = {
  WeightClass: string
  pct_pre2025: number | null
  pct_2025: number | null
  pct_2027_today: number | null
}

export type QtBlocksResponse = {
  F_Regionals: QtBlockRow[]
  F_Nationals: QtBlockRow[]
  M_Regionals: QtBlockRow[]
  M_Nationals: QtBlockRow[]
}

export function fetchQtBlocks(): Promise<QtBlocksResponse> {
  return getJson<QtBlocksResponse>(`${API_BASE}/api/qt/blocks`)
}

// ---------- QT standards ----------

export type QtStandardRow = {
  Sex: string
  Level: string  // 'Regionals' or 'Nationals'
  WeightClass: string
  QT_pre2025: number | null
  QT_2025: number | null
  QT_2027: number | null
}

export function fetchQtStandards(): Promise<QtStandardRow[]> {
  return getJson<QtStandardRow[]>(`${API_BASE}/api/qt/standards`)
}

// ---------- Lifter history ----------

export type LifterMeet = {
  Name: string
  Sex: string
  Federation: string | null
  Country: string | null
  Equipment: string | null
  Tested: string | null
  Event: string | null
  Division: string | null
  Age: number | null
  CanonicalWeightClass: string | null
  Date: string  // ISO yyyy-mm-dd
  TotalKg: number
  Best3SquatKg: number | null
  Best3BenchKg: number | null
  Best3DeadliftKg: number | null
  Dots: number | null
  MeetName: string | null
  MeetCountry: string | null
  TotalDiffFromFirst: number
  DaysFromFirst: number
  is_pr: boolean
  class_changed: boolean
}

export type WeightClassChange = {
  date: string
  from_class: string
  to_class: string
}

export type ProjectionPoint = {
  days_from_first: number
  projected_total: number
  upper: number
  lower: number
}

export type LifterProjection = {
  slope_kg_per_day: number
  slope_kg_per_month: number
  residual_std: number
  project_months: number
  points: ProjectionPoint[]
}

export type LifterHistory = {
  name: string
  found: boolean
  sex?: string
  federation?: string | null
  country?: string | null
  latest_equipment?: string | null
  latest_weight_class?: string | null
  meet_count?: number
  best_total_kg?: number
  rate_kg_per_month?: number | null
  weight_class_changes?: WeightClassChange[]
  projection?: LifterProjection | null
  percentile_rank?: {
    percentile: number
    cohort_size: number
    cohort_desc: string
  } | null
  meets: LifterMeet[]
}

export function fetchLifterHistory(name: string): Promise<LifterHistory> {
  return getJson<LifterHistory>(
    `${API_BASE}/api/lifters/${encodeURIComponent(name)}/history`,
  )
}

// ---------- Manual trajectory ----------

export type ManualEntry = {
  date: string  // ISO yyyy-mm-dd
  total_kg: number
  bodyweight_kg?: number | null
  weight_class?: string | null
  squat_kg?: number | null
  bench_kg?: number | null
  deadlift_kg?: number | null
  meet_name?: string | null
}

export type ManualRequest = {
  name: string
  sex: string
  equipment?: string
  event?: string
  entries: ManualEntry[]
}

export function postManualTrajectory(req: ManualRequest): Promise<LifterHistory> {
  return fetch(`${API_BASE}/api/manual/trajectory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  }).then(async (res) => {
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`)
    return res.json()
  })
}
