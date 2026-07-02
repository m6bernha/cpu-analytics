// Client-side CSV download built from already-fetched query data.
// No backend round trip: serialize, blob, temporary anchor click.

type CsvCell = string | number | null | undefined

function escapeCell(cell: CsvCell): string {
  if (cell == null) return ''
  const s = String(cell)
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`
  }
  return s
}

export function downloadCsv(
  filename: string,
  headers: string[],
  rows: CsvCell[][],
): void {
  const lines = [headers, ...rows].map((row) => row.map(escapeCell).join(','))
  // \r\n per RFC 4180; BOM so Excel detects UTF-8.
  const blob = new Blob(['﻿' + lines.join('\r\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

/** 'Matthias Bernhard' -> 'matthias-bernhard' for filenames. */
export function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
