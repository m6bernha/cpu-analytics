// Scout tab — Vireo-style meet scouting report generator.
//
// Form panel above the rendered report. The form is hidden under @media
// print so users can browser-print the report straight to PDF as a v1
// stopgap (Phase 4 of the Scout plan is a native PDF export).
//
// Roster format in the textarea: one name per line. Lines starting with
// `@` are homies (highlighted in the report). Names that don't match
// OpenIPF fall to the Unranked appendix.

import { useMemo, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import {
  postScoutReport,
  type ScoutClassBlock,
  type ScoutMeetReport,
  type ScoutMeetRequest,
  type ScoutStatusTag,
} from '../lib/api'
import { exportReportPdf } from '../lib/exportReportPdf'
import { fmtInt, fmtKg } from '../lib/format'
import {
  EMPTY_OVERRIDE,
  buildRosterEntries,
  parseRoster,
  type OverrideDraft,
} from '../lib/scoutOverrides'

interface ScoutProps {
  isActive: boolean
}

// Scout was locked as WIP from 2026-07-02 while the roster fan-out got
// validated. Unlocked 2026-08-04 after the manual-override UI, native PDF
// export, and the real-roster accuracy pass landed. Flip to true to
// re-lock the form and report rendering.
const SCOUT_LOCKED = false

interface FormState {
  meetName: string
  federation: string
  location: string
  meetDate: string
  generatorName: string
  generatorBrand: string
  rosterText: string
}

const INITIAL_FORM: FormState = {
  meetName: '',
  federation: 'CPU',
  location: '',
  meetDate: '',
  generatorName: '',
  generatorBrand: 'Vireo Powerlifting',
  rosterText: '',
}

function statusToneClass(tag: ScoutStatusTag): string {
  switch (tag) {
    case 'Veteran':
      return 'bg-orange-500/15 text-orange-300 border-orange-500/30'
    case 'Established':
      return 'bg-blue-500/15 text-blue-300 border-blue-500/30'
    case 'Developing':
      return 'bg-teal-500/15 text-teal-300 border-teal-500/30'
    case 'Rookie':
      return 'bg-violet-500/15 text-violet-300 border-violet-500/30'
    case 'Frozen':
      return 'bg-zinc-700/40 text-zinc-300 border-zinc-600/40'
    case 'Unmatched':
    default:
      return 'bg-zinc-800 text-zinc-400 border-zinc-700'
  }
}

function fmtDateRelative(iso: string | null, days: number | null): string {
  if (!iso) return '—'
  if (days === null) return iso
  if (days <= 30) return `${iso} (${days}d)`
  if (days <= 365) return `${iso} (${Math.round(days / 30.44)}mo)`
  return `${iso} (${(days / 365.25).toFixed(1)}yr)`
}


export default function Scout({ isActive }: ScoutProps) {
  const [form, setForm] = useState<FormState>(INITIAL_FORM)
  const [overrides, setOverrides] = useState<OverrideDraft[]>([])

  const mutation = useMutation<ScoutMeetReport, Error, ScoutMeetRequest>({
    mutationFn: postScoutReport,
  })

  const roster = useMemo(() => parseRoster(form.rosterText), [form.rosterText])

  const canSubmit =
    form.meetName.trim().length > 0
    && /^\d{4}-\d{2}-\d{2}$/.test(form.meetDate)
    && roster.length > 0

  const updateOverride = (i: number, patch: Partial<OverrideDraft>) =>
    setOverrides(overrides.map((d, j) => (j === i ? { ...d, ...patch } : d)))
  const removeOverride = (i: number) =>
    setOverrides(overrides.filter((_, j) => j !== i))
  const seedOverride = (name: string) =>
    setOverrides((prev) =>
      prev.some((d) => d.name.trim().toLowerCase() === name.toLowerCase())
        ? prev
        : [...prev, { ...EMPTY_OVERRIDE, name }],
    )

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (SCOUT_LOCKED || !canSubmit) return
    mutation.mutate({
      meet_name: form.meetName.trim(),
      federation: form.federation.trim() || 'CPU',
      location: form.location.trim(),
      meet_date: form.meetDate,
      generator_name: form.generatorName.trim(),
      generator_brand: form.generatorBrand.trim(),
      roster: buildRosterEntries(roster, overrides),
    })
  }

  const report = mutation.data

  // Native PDF export (Phase 4). Captures the rendered (and sex-filtered)
  // report DOM, so the download matches what is on screen.
  const reportRef = useRef<HTMLDivElement | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const handleExportPdf = async () => {
    if (!reportRef.current || !report) return
    setExporting(true)
    setExportError(null)
    try {
      const slug =
        report.request.meet_name
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, '') || 'scout-report'
      await exportReportPdf(
        reportRef.current,
        `scout-${slug}-${report.request.meet_date}.pdf`,
      )
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'PDF export failed')
    } finally {
      setExporting(false)
    }
  }

  // Display-only sex filter over the generated report. Rows with unknown
  // sex (manual overrides without one) are hidden while a filter is on.
  const [sexFilter, setSexFilter] = useState<'all' | 'F' | 'M'>('all')
  const visibleReport = useMemo<ScoutMeetReport | undefined>(() => {
    if (!report || sexFilter === 'all') return report
    const keep = (a: { sex: string | null }) => a.sex === sexFilter
    const filterBlocks = (blocks: ScoutClassBlock[]) =>
      blocks
        .map((cb) => ({ ...cb, athletes: cb.athletes.filter(keep) }))
        .filter((cb) => cb.athletes.length > 0)
        .map((cb) => ({ ...cb, n_athletes: cb.athletes.length }))
    return {
      ...report,
      class_blocks: filterBlocks(report.class_blocks),
      closest_battles: filterBlocks(report.closest_battles),
      homies: report.homies.filter(keep),
    }
  }, [report, sexFilter])

  return (
    <div className={isActive ? 'space-y-6' : 'space-y-6 hidden'}>
      {SCOUT_LOCKED && (
        <section className="rounded border border-amber-500/30 bg-amber-500/5 p-4 max-w-3xl">
          <h2 className="text-amber-300 text-base font-semibold mb-2">
            Scout is a work in progress
          </h2>
          <div className="text-zinc-300 text-sm leading-relaxed space-y-2">
            <p>
              This page is not ready to use yet. It is being rebuilt and
              validated before it opens up.
            </p>
            <p>
              The goal: paste the roster of an upcoming meet and get a
              coach-ready scouting report in seconds. Projected totals with
              95 percent prediction intervals for every athlete, per-class
              rankings with the gap between first and second, the closest
              projected battles across the meet, and status tags that
              separate rookies, established lifters, and veterans returning
              from a layoff.
            </p>
            <p>
              The projection engine behind it already powers the Athlete
              Projection tab. The roster layer on top still needs work:
              name matching, stale-lifter handling, and report accuracy
              across a full field. Until that holds up, the form below is
              a disabled preview.
            </p>
          </div>
        </section>
      )}

      <section
        className={
          SCOUT_LOCKED
            ? 'scout-form opacity-40 pointer-events-none select-none'
            : 'scout-form'
        }
        aria-hidden={SCOUT_LOCKED}
      >
        <h2 className="text-zinc-100 text-base font-semibold mb-1">
          Meet Scout
        </h2>
        <p className="text-zinc-500 text-xs mb-4 max-w-2xl">
          Paste a roster and generate a per-meet scouting report: per-class
          projected gaps, status tags, homies highlighted, unranked appendix.
          Names not found in OpenIPF fall to the Unranked Field section.
        </p>

        <form onSubmit={handleSubmit}>
          <fieldset
            disabled={SCOUT_LOCKED}
            className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-3xl"
          >
          <label className="text-xs text-zinc-400 space-y-1">
            <span>Meet name *</span>
            <input
              type="text"
              required
              maxLength={200}
              value={form.meetName}
              onChange={(e) => setForm({ ...form, meetName: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-600"
              placeholder="e.g. Sunny Daze 2026"
            />
          </label>
          <label className="text-xs text-zinc-400 space-y-1">
            <span>Meet date * (YYYY-MM-DD)</span>
            <input
              type="date"
              required
              value={form.meetDate}
              onChange={(e) => setForm({ ...form, meetDate: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-600"
            />
          </label>
          <label className="text-xs text-zinc-400 space-y-1">
            <span>Federation</span>
            <input
              type="text"
              maxLength={50}
              value={form.federation}
              onChange={(e) => setForm({ ...form, federation: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-600"
            />
          </label>
          <label className="text-xs text-zinc-400 space-y-1">
            <span>Location</span>
            <input
              type="text"
              maxLength={200}
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-600"
              placeholder="City, Province"
            />
          </label>
          <label className="text-xs text-zinc-400 space-y-1">
            <span>Generator name</span>
            <input
              type="text"
              maxLength={100}
              value={form.generatorName}
              onChange={(e) => setForm({ ...form, generatorName: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-600"
              placeholder="Your name (optional)"
            />
          </label>
          <label className="text-xs text-zinc-400 space-y-1">
            <span>Generator brand</span>
            <input
              type="text"
              maxLength={100}
              value={form.generatorBrand}
              onChange={(e) => setForm({ ...form, generatorBrand: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 focus:outline-none focus:border-zinc-600"
            />
          </label>
          <label className="text-xs text-zinc-400 space-y-1 md:col-span-2">
            <span>
              Roster ({roster.length} {roster.length === 1 ? 'name' : 'names'}) *
              <span className="text-zinc-500 ml-2">
                One name per line. Prefix with @ to tag as a homie.
              </span>
            </span>
            <textarea
              required
              rows={10}
              value={form.rosterText}
              onChange={(e) => setForm({ ...form, rosterText: e.target.value })}
              className="block w-full bg-zinc-900 border border-zinc-800 rounded px-2 py-1.5 text-sm text-zinc-100 font-mono focus:outline-none focus:border-zinc-600"
              placeholder={'Jane Doe\nJohn Smith\n@My Lifter'}
            />
          </label>

          <div className="md:col-span-2 space-y-2">
            <div className="flex items-center gap-3 flex-wrap">
              <span className="text-xs text-zinc-400">
                Manual overrides ({overrides.length})
              </span>
              <button
                type="button"
                onClick={() => setOverrides([...overrides, { ...EMPTY_OVERRIDE }])}
                className="px-2 py-0.5 rounded text-xs border border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-zinc-100"
              >
                Add override
              </button>
              <span className="text-zinc-500 text-xs">
                For lifters missing from OpenIPF. Best total stands in as the
                projection. Matches a roster line by name, or adds the lifter
                if no line matches.
              </span>
            </div>
            {overrides.map((d, i) => (
              <div
                key={i}
                className="grid grid-cols-2 md:grid-cols-9 gap-2 rounded border border-zinc-800 bg-zinc-900/50 p-2"
              >
                <label className="text-[10px] text-zinc-500 space-y-0.5 col-span-2">
                  <span>Name *</span>
                  <input
                    type="text"
                    maxLength={100}
                    value={d.name}
                    onChange={(e) => updateOverride(i, { name: e.target.value })}
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                  />
                </label>
                <label className="text-[10px] text-zinc-500 space-y-0.5">
                  <span>Total kg *</span>
                  <input
                    type="number"
                    min={0}
                    max={1500}
                    step="0.5"
                    value={d.bestTotal}
                    onChange={(e) => updateOverride(i, { bestTotal: e.target.value })}
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                  />
                </label>
                <label className="text-[10px] text-zinc-500 space-y-0.5">
                  <span>S kg</span>
                  <input
                    type="number"
                    min={0}
                    max={600}
                    step="0.5"
                    value={d.squat}
                    onChange={(e) => updateOverride(i, { squat: e.target.value })}
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                  />
                </label>
                <label className="text-[10px] text-zinc-500 space-y-0.5">
                  <span>B kg</span>
                  <input
                    type="number"
                    min={0}
                    max={400}
                    step="0.5"
                    value={d.bench}
                    onChange={(e) => updateOverride(i, { bench: e.target.value })}
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                  />
                </label>
                <label className="text-[10px] text-zinc-500 space-y-0.5">
                  <span>D kg</span>
                  <input
                    type="number"
                    min={0}
                    max={600}
                    step="0.5"
                    value={d.deadlift}
                    onChange={(e) => updateOverride(i, { deadlift: e.target.value })}
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                  />
                </label>
                <label className="text-[10px] text-zinc-500 space-y-0.5">
                  <span>Class</span>
                  <input
                    type="text"
                    maxLength={20}
                    value={d.weightClass}
                    onChange={(e) => updateOverride(i, { weightClass: e.target.value })}
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                    placeholder="83"
                  />
                </label>
                <label className="text-[10px] text-zinc-500 space-y-0.5">
                  <span>Sex</span>
                  <select
                    value={d.sex}
                    onChange={(e) =>
                      updateOverride(i, { sex: e.target.value as OverrideDraft['sex'] })
                    }
                    className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1.5 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                  >
                    <option value="">—</option>
                    <option value="F">F</option>
                    <option value="M">M</option>
                  </select>
                </label>
                <div className="flex items-end gap-1">
                  <label className="text-[10px] text-zinc-500 space-y-0.5 flex-1">
                    <span>Last meet</span>
                    <input
                      type="date"
                      value={d.lastMeetDate}
                      onChange={(e) => updateOverride(i, { lastMeetDate: e.target.value })}
                      className="block w-full bg-zinc-900 border border-zinc-800 rounded px-1 py-1 text-xs text-zinc-100 focus:outline-none focus:border-zinc-600"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => removeOverride(i)}
                    aria-label={`Remove override ${d.name || i + 1}`}
                    className="pb-1 text-zinc-500 hover:text-red-400 text-sm leading-none"
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
          <div className="md:col-span-2 flex items-center gap-3">
            <button
              type="submit"
              disabled={!canSubmit || mutation.isPending}
              className="px-4 py-1.5 rounded text-sm bg-orange-500 text-zinc-950 font-medium hover:bg-orange-400 disabled:bg-zinc-800 disabled:text-zinc-500 disabled:cursor-not-allowed"
            >
              {mutation.isPending ? 'Generating…' : 'Generate report'}
            </button>
            {mutation.error && (
              <span className="text-xs text-red-400">
                {mutation.error.message}
              </span>
            )}
          </div>
          </fieldset>
        </form>
      </section>

      {!SCOUT_LOCKED && report && (
        <div className="print:hidden flex items-center gap-2 flex-wrap">
          <span className="text-zinc-500 text-xs uppercase tracking-wide">Show</span>
          {(
            [
              ['all', 'All'],
              ['F', 'Women'],
              ['M', 'Men'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => setSexFilter(value)}
              aria-pressed={sexFilter === value}
              className={
                'px-3 py-1 rounded text-xs transition-colors ' +
                (sexFilter === value
                  ? 'bg-zinc-800 text-zinc-100'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900')
              }
            >
              {label}
            </button>
          ))}
          <span className="flex-1" />
          {exportError && (
            <span className="text-xs text-red-400">{exportError}</span>
          )}
          <button
            onClick={handleExportPdf}
            disabled={exporting}
            className="px-3 py-1 rounded text-xs border border-zinc-700 text-zinc-300 hover:border-zinc-500 hover:text-zinc-100 disabled:text-zinc-600 disabled:cursor-wait"
          >
            {exporting ? 'Exporting…' : 'Download PDF'}
          </button>
        </div>
      )}

      {!SCOUT_LOCKED && visibleReport && (
        <div ref={reportRef}>
          <ReportView report={visibleReport} onAddOverride={seedOverride} />
        </div>
      )}
    </div>
  )
}


function ReportView({
  report,
  onAddOverride,
}: {
  report: ScoutMeetReport
  onAddOverride?: (name: string) => void
}) {
  const { request: req } = report
  return (
    <article className="scout-report space-y-6 text-zinc-200">
      <header className="border-b border-zinc-800 pb-3">
        <h1 className="text-xl font-semibold">
          {req.generator_brand || 'Vireo Powerlifting'} — {req.meet_name} Scouting Report
        </h1>
        <div className="text-xs text-zinc-500 mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {req.federation && <span>{req.federation}</span>}
          {req.location && <span>{req.location}</span>}
          <span>Meet date: {req.meet_date}</span>
          <span>Horizon: {report.horizon_days} days ({report.horizon_months} mo)</span>
          <span>Generated: {report.generated_at}</span>
          <span>{report.n_athletes_matched} matched / {report.unranked.length} unranked</span>
          {req.generator_name && <span>By {req.generator_name}</span>}
        </div>
      </header>

      {report.homies.length > 0 && (
        <section>
          <h2 className="text-zinc-100 text-base font-semibold mb-2">The Homies</h2>
          <div className="overflow-x-auto">
            <table className="text-xs min-w-full">
              <thead className="text-zinc-400 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="text-left pr-3 pb-1">Homie</th>
                  <th className="text-left pr-3 pb-1">Class</th>
                  <th className="text-left pr-3 pb-1">Status</th>
                  <th className="text-right pr-3 pb-1">Projected total</th>
                  <th className="text-right pr-3 pb-1">95% PI</th>
                </tr>
              </thead>
              <tbody className="text-zinc-200">
                {report.homies.map((h) => (
                  <tr key={h.name} className="border-t border-zinc-900">
                    <td className="pr-3 py-1 font-medium">{h.name}</td>
                    <td className="pr-3 py-1">{h.weight_class || '—'}</td>
                    <td className="pr-3 py-1">
                      <StatusChip tag={h.status_tag} />
                    </td>
                    <td className="pr-3 py-1 text-right tabular-nums">
                      {fmtKg(h.projected_total_kg, 1)}
                    </td>
                    <td className="pr-3 py-1 text-right tabular-nums text-zinc-400">
                      ±{fmtKg(h.projected_pi_half_kg, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <details className="mt-2">
        <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
          Methodology
        </summary>
        <div className="text-zinc-500 text-xs mt-2 max-w-2xl">
          <p>{report.methodology}</p>
        </div>
      </details>

      {report.closest_battles.length > 0 && (
        <section>
          <h2 className="text-zinc-100 text-base font-semibold mb-2">
            Closest projected battles
          </h2>
          <div className="overflow-x-auto">
            <table className="text-xs min-w-full">
              <thead className="text-zinc-400 text-[10px] uppercase tracking-wider">
                <tr>
                  <th className="text-left pr-3 pb-1">Rank</th>
                  <th className="text-left pr-3 pb-1">Class</th>
                  <th className="text-right pr-3 pb-1">Athletes</th>
                  <th className="text-right pr-3 pb-1">Gap (kg)</th>
                  <th className="text-left pr-3 pb-1">Top contender</th>
                </tr>
              </thead>
              <tbody className="text-zinc-200">
                {report.closest_battles.map((cb, i) => (
                  <tr key={`${cb.weight_class}-${i}`} className="border-t border-zinc-900">
                    <td className="pr-3 py-1 tabular-nums">{i + 1}</td>
                    <td className="pr-3 py-1">{cb.weight_class || '—'}</td>
                    <td className="pr-3 py-1 text-right tabular-nums">{cb.n_athletes}</td>
                    <td className="pr-3 py-1 text-right tabular-nums text-orange-300">
                      {fmtKg(cb.projected_gap_kg, 1)}
                    </td>
                    <td className="pr-3 py-1">
                      {cb.athletes[0]?.name || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="space-y-6">
        <h2 className="text-zinc-100 text-base font-semibold">Per-class deep dive</h2>
        <p className="text-zinc-500 text-xs -mt-4 max-w-2xl">
          Classes are ordered by the projected gap between #1 and #2, tightest
          battle first. Projections run each athlete's per-lift Engine C
          forecast to meet day; ±PI is the 95% interval summed across S/B/D.
          Athletes more than 2 years out from their last meet stay listed but
          are excluded from the gap calculation.
        </p>
        {report.class_blocks.map((cb, i) => (
          <ClassBlock key={`class-${cb.weight_class}-${i}`} block={cb} rank={i + 1} />
        ))}
      </section>

      {report.unranked.length > 0 && (
        <section>
          <h2 className="text-zinc-100 text-base font-semibold mb-2">
            Unranked Field
          </h2>
          <p className="text-zinc-500 text-xs mb-2">
            Roster names without an OpenIPF match. Listed alphabetically.
          </p>
          <ul className="text-zinc-300 text-xs grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-1">
            {[...report.unranked].sort().map((n) => (
              <li key={n} className="flex items-center gap-2">
                <span>{n}</span>
                {onAddOverride && (
                  <button
                    type="button"
                    onClick={() => onAddOverride(n)}
                    className="print:hidden text-[10px] text-zinc-500 hover:text-orange-300 border border-zinc-800 hover:border-zinc-600 rounded px-1"
                    title="Seed a manual override in the form above, then regenerate"
                  >
                    Add data
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <footer className="border-t border-zinc-900 pt-3 text-zinc-500 text-xs">
        Informational, not a prediction. Projections derive from the most
        recent Canadian IPF-affiliated meet history per athlete. Athletes can
        and do change preparation. Cite responsibly.
      </footer>
    </article>
  )
}


function ClassBlock({ block, rank }: { block: ScoutClassBlock; rank: number }) {
  return (
    <div>
      <h3 className="text-zinc-200 text-sm font-medium mb-1.5">
        #{rank} · {block.weight_class || '(unclassified)'} kg · {block.n_athletes}{' '}
        {block.n_athletes === 1 ? 'athlete' : 'athletes'}
        {block.projected_gap_kg !== null && (
          <span className="ml-2 text-zinc-500">
            projected gap {fmtKg(block.projected_gap_kg, 1)} kg
          </span>
        )}
      </h3>
      <div className="overflow-x-auto">
        <table className="text-xs min-w-full">
          <thead className="text-zinc-400 text-[10px] uppercase tracking-wider">
            <tr>
              <th className="text-left pr-3 pb-1">#</th>
              <th className="text-left pr-3 pb-1">Athlete</th>
              <th className="text-left pr-3 pb-1">Div</th>
              <th className="text-left pr-3 pb-1">Last meet</th>
              <th className="text-right pr-3 pb-1">Best total</th>
              <th className="text-right pr-3 pb-1">S</th>
              <th className="text-right pr-3 pb-1">B</th>
              <th className="text-right pr-3 pb-1">D</th>
              <th className="text-right pr-3 pb-1">Projected</th>
              <th className="text-right pr-3 pb-1">±PI</th>
              <th className="text-left pr-3 pb-1">Status</th>
              <th className="text-left pr-3 pb-1">Notes</th>
            </tr>
          </thead>
          <tbody className="text-zinc-200">
            {block.athletes.map((a, i) => (
              <tr
                key={`${a.name}-${i}`}
                className={
                  'border-t border-zinc-900 ' +
                  (a.is_homie ? 'bg-orange-500/5' : '')
                }
              >
                <td className="pr-3 py-1 tabular-nums">{i + 1}</td>
                <td className={'pr-3 py-1 ' + (a.is_homie ? 'font-medium text-orange-200' : '')}>
                  {a.name}
                </td>
                <td className="pr-3 py-1 text-zinc-400">{a.division || '—'}</td>
                <td className="pr-3 py-1 text-zinc-400">
                  {fmtDateRelative(a.last_meet_date, a.days_since_last_meet)}
                </td>
                <td className="pr-3 py-1 text-right tabular-nums">
                  {fmtKg(a.best_total_kg, 1)}
                </td>
                <td className="pr-3 py-1 text-right tabular-nums text-zinc-400">
                  {fmtKg(a.squat_best_kg, 1)}
                </td>
                <td className="pr-3 py-1 text-right tabular-nums text-zinc-400">
                  {fmtKg(a.bench_best_kg, 1)}
                </td>
                <td className="pr-3 py-1 text-right tabular-nums text-zinc-400">
                  {fmtKg(a.deadlift_best_kg, 1)}
                </td>
                <td className="pr-3 py-1 text-right tabular-nums">
                  {fmtKg(a.projected_total_kg, 1)}
                </td>
                <td className="pr-3 py-1 text-right tabular-nums text-zinc-400">
                  {a.projected_pi_half_kg !== null
                    ? `±${fmtKg(a.projected_pi_half_kg, 1)}`
                    : '—'}
                </td>
                <td className="pr-3 py-1">
                  <StatusChip tag={a.status_tag} />
                </td>
                <td className="pr-3 py-1 text-zinc-400">
                  {a.inline_tags.length > 0 ? a.inline_tags.join('; ') : ''}
                  {a.glp_score !== null && (
                    <span className="ml-2 text-zinc-500">GLP {fmtInt(a.glp_score)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


function StatusChip({ tag }: { tag: ScoutStatusTag }) {
  return (
    <span
      className={
        'inline-block px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider border ' +
        statusToneClass(tag)
      }
    >
      {tag}
    </span>
  )
}
