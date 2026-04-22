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
  division: string[]
  weight_class: { M: string[]; F: string[] }
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
  metric: string
  y_label: string
  points: ProgressionPoint[]
  trend: ProgressionTrend | null
  projection: CohortProjection | null
  n_lifters: number
  n_meets: number
  n_lifters_before_age_filter: number
  n_all_lifters: number
  avg_first_value: number | null
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
  'division',
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
  x_axis?: string
  metric?: string
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
  tested?: string
  event?: string
  weight_class?: string
  division?: string
  x_axis?: string
  max_gap_months?: string
  same_class_only?: string
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

export type QtBlocksMeta = {
  division: string
  using_open_fallback: boolean
}

export type QtBlocksResponse = {
  F_Regionals: QtBlockRow[]
  F_Nationals: QtBlockRow[]
  M_Regionals: QtBlockRow[]
  M_Nationals: QtBlockRow[]
  meta?: QtBlocksMeta
}

export function fetchQtBlocks(division: string = 'Open'): Promise<QtBlocksResponse> {
  const params = new URLSearchParams({ division })
  return getJson<QtBlocksResponse>(`${API_BASE}/api/qt/blocks?${params}`)
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

// ---------- Live-scrape QT (2026+) ----------
//
// These endpoints read from qt_current.csv, published weekly by the
// qt_refresh GHA workflow from scraped powerlifting.ca PDFs. When the
// CSV isn't yet present (first cold start before the scraper has run,
// or release asset missing), live_data_available is false and the
// frontend should hide the live panel.

export type QtLiveFilters = {
  live_data_available: boolean
  sexes?: string[]
  levels?: string[]
  regions?: string[]
  divisions?: string[]
  effective_years?: number[]
  fetched_at?: string | null
}

export function fetchQtLiveFilters(): Promise<QtLiveFilters> {
  return getJson<QtLiveFilters>(`${API_BASE}/api/qt/live/filters`)
}

export type QtLiveCoverageRow = {
  weight_class: string
  qt: number
  n_lifters: number
  n_meeting_qt: number
  pct_meeting_qt: number | null
}

export type QtLiveCoverageResponse = {
  rows: QtLiveCoverageRow[]
  meta: {
    live_data_available: boolean
    filters: {
      sex: string
      level: string
      effective_year: number
      division: string
      region: string | null
      equipment: string
      event: string
    }
    fetched_at: string | null
  }
}

export type QtLiveCoverageParams = {
  sex: 'M' | 'F'
  level: 'Nationals' | 'Regionals'
  effective_year: number
  division?: string
  region?: string | null
  equipment?: string
  event?: string
}

export function fetchQtLiveCoverage(
  p: QtLiveCoverageParams,
): Promise<QtLiveCoverageResponse> {
  const params = new URLSearchParams({
    sex: p.sex,
    level: p.level,
    effective_year: String(p.effective_year),
    division: p.division ?? 'Open',
    equipment: p.equipment ?? 'Classic',
    event: p.event ?? 'SBD',
  })
  if (p.region) params.set('region', p.region)
  return getJson<QtLiveCoverageResponse>(
    `${API_BASE}/api/qt/live/coverage?${params}`,
  )
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
  TotalKg: number | null
  Best3SquatKg: number | null
  Best3BenchKg: number | null
  Best3DeadliftKg: number | null
  Goodlift: number | null
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
  // Either total_kg OR all three of squat_kg/bench_kg/deadlift_kg required.
  // Backend reconciles: computes total from lifts when omitted, rejects
  // mismatches when both are supplied.
  total_kg?: number | null
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

export async function postManualTrajectory(req: ManualRequest): Promise<LifterHistory> {
  const res = await fetch(`${API_BASE}/api/manual/trajectory`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) {
    // Surface FastAPI / Pydantic validation messages so the user sees
    // "Total does not match sum of lifts" instead of a bare 422.
    let detail = ''
    try {
      const body = await res.json()
      if (body?.detail) {
        if (typeof body.detail === 'string') {
          detail = body.detail
        } else if (Array.isArray(body.detail)) {
          detail = body.detail
            .map((d: { msg?: string; loc?: (string | number)[] }) =>
              d?.msg ? `${d.msg}` : JSON.stringify(d),
            )
            .join('; ')
        } else {
          detail = JSON.stringify(body.detail)
        }
      }
    } catch {
      // Body was not JSON; fall through to generic HTTP error.
    }
    throw new Error(detail || `HTTP ${res.status} ${res.statusText}`)
  }
  return res.json()
}
