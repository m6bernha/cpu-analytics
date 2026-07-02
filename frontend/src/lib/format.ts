// Shared display formatters. All date helpers parse the ISO string
// directly instead of going through `new Date(iso)`, which would
// interpret the value as UTC midnight and can round back to the
// previous day depending on the viewer's timezone.

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/** 'yyyy-mm-dd' -> 'Mon D, YYYY'. Falls back to the raw string on bad input. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parts = iso.slice(0, 10).split('-').map(Number)
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso
  const [y, m, d] = parts
  return `${MONTHS[m - 1]} ${d}, ${y}`
}

/** 'yyyy-mm-dd' -> "Mon 'YY" (compact axis/chip form). */
export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return ''
  const parts = iso.slice(0, 10).split('-').map(Number)
  if (parts.length !== 3 || parts.some(Number.isNaN)) return iso
  const [y, m] = parts
  return `${MONTHS[m - 1]} '${String(y).slice(-2)}`
}

/** Kilogram value with fixed digits; em dash for null/NaN/inf. */
export function fmtKg(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}

/** Rounded integer; em dash for null/undefined. */
export function fmtInt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return String(Math.round(v))
}
