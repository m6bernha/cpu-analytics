import { useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { type AthleteProjectionResponse } from '../../lib/api'

type LiftKey = 'total' | 'squat' | 'bench' | 'deadlift'

const COLORS = {
  history: '#569cd6',
  projected: '#818CF8',
  piBand: '#818CF8',
  reference: '#4ec9b0',
  grid: '#3f3f46',
}

type ChartRow = {
  days: number
  date?: string
  daysSinceLastMeet?: number
  history?: number
  projected?: number
  piBand?: [number, number]
}

function addDaysISO(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + Math.round(days))
  const yy = dt.getUTCFullYear()
  const mm = String(dt.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(dt.getUTCDate()).padStart(2, '0')
  return `${yy}-${mm}-${dd}`
}

function fmtDateLong(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  return dt.toLocaleDateString('en-CA', {
    timeZone: 'UTC',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function liftLabel(liftKey: LiftKey): string {
  switch (liftKey) {
    case 'total':
      return 'Total'
    case 'squat':
      return 'Squat'
    case 'bench':
      return 'Bench'
    case 'deadlift':
      return 'Deadlift'
  }
}

function buildChartData(
  data: AthleteProjectionResponse,
  liftKey: LiftKey,
): ChartRow[] {
  const rows: ChartRow[] = []

  const firstMeetDate: string | undefined = data.total_history?.[0]?.date
  const lastTotalHistory =
    data.total_history?.[data.total_history.length - 1]
  const lastMeetDay: number | undefined = lastTotalHistory?.days_from_first

  const dateFor = (days: number): string | undefined =>
    firstMeetDate ? addDaysISO(firstMeetDate, days) : undefined
  const sinceLastFor = (days: number): number | undefined =>
    lastMeetDay != null ? Math.round(days - lastMeetDay) : undefined

  if (liftKey === 'total') {
    for (const h of data.total_history ?? []) {
      rows.push({
        days: h.days_from_first,
        date: h.date,
        daysSinceLastMeet: sinceLastFor(h.days_from_first),
        history: h.total_kg,
      })
    }
    const last = data.total_history?.[data.total_history.length - 1]
    if (last) {
      rows.push({
        days: last.days_from_first,
        date: last.date,
        daysSinceLastMeet: 0,
        projected: last.total_kg,
        piBand: [last.total_kg, last.total_kg],
      })
    }
    for (const p of data.total_projected_points ?? []) {
      rows.push({
        days: p.days_from_first,
        date: dateFor(p.days_from_first),
        daysSinceLastMeet: sinceLastFor(p.days_from_first),
        projected: p.projected_kg,
        piBand: [p.lower_kg, p.upper_kg],
      })
    }
  } else {
    const lift = data.lifts?.[liftKey]
    if (!lift) return rows
    const liftHistory = lift.history ?? []
    if (liftHistory.length > 0) {
      for (const h of liftHistory) {
        rows.push({
          days: h.days_from_first,
          date: h.date,
          daysSinceLastMeet: sinceLastFor(h.days_from_first),
          history: h.kg,
        })
      }
      const last = liftHistory[liftHistory.length - 1]
      rows.push({
        days: last.days_from_first,
        date: last.date,
        daysSinceLastMeet: 0,
        projected: last.kg,
        piBand: [last.kg, last.kg],
      })
    } else if (lift.current_level != null && lift.last_meet_day != null) {
      rows.push({
        days: lift.last_meet_day,
        date: dateFor(lift.last_meet_day),
        daysSinceLastMeet: sinceLastFor(lift.last_meet_day),
        history: lift.current_level,
        projected: lift.current_level,
        piBand: [lift.current_level, lift.current_level],
      })
    }
    for (const p of lift.projected_points) {
      rows.push({
        days: p.days_from_first,
        date: dateFor(p.days_from_first),
        daysSinceLastMeet: sinceLastFor(p.days_from_first),
        projected: p.projected_kg,
        piBand: [p.lower_kg, p.upper_kg],
      })
    }
  }
  rows.sort((a, b) => a.days - b.days)
  return rows
}

function ProjectionTooltip({
  active,
  payload,
  label,
  liftLabel: labelText,
}: {
  active?: boolean
  payload?: Array<{ payload?: ChartRow }>
  label?: number | string
  liftLabel: string
}) {
  if (!active || !payload || payload.length === 0) return null
  const row = payload[0].payload as ChartRow | undefined
  if (!row) return null

  const sinceMeet = row.daysSinceLastMeet
  const sinceLabel =
    sinceMeet == null
      ? null
      : sinceMeet === 0
        ? 'Last meet'
        : sinceMeet > 0
          ? `${sinceMeet} day${sinceMeet === 1 ? '' : 's'} since last meet`
          : `${-sinceMeet} day${-sinceMeet === 1 ? '' : 's'} before last meet`

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-xs text-zinc-200">
      <div className="text-zinc-400">Day {Math.round(Number(label ?? 0))}</div>
      {row.history != null && (
        <div>
          <span className="text-zinc-400">{labelText}: </span>
          <span className="text-zinc-100 font-medium">{row.history.toFixed(1)} kg</span>
        </div>
      )}
      {row.projected != null && (
        <div>
          <span className="text-zinc-400">Projected: </span>
          <span className="text-zinc-100 font-medium">{row.projected.toFixed(1)} kg</span>
        </div>
      )}
      {row.piBand && row.piBand[0] !== row.piBand[1] && (
        <div className="text-zinc-500">
          PI: [{row.piBand[0].toFixed(1)}, {row.piBand[1].toFixed(1)}]
        </div>
      )}
      {(row.date || sinceLabel) && (
        <div className="mt-1 pt-1 border-t border-zinc-800 text-zinc-500">
          {row.date && <div>{fmtDateLong(row.date)}</div>}
          {sinceLabel && <div>{sinceLabel}</div>}
        </div>
      )}
    </div>
  )
}

function ProjectionChart({
  data,
  liftKey,
  isActive,
  showQt,
  effectiveYear,
  regionalsQtKg,
  nationalsQtKg,
}: {
  data: AthleteProjectionResponse
  liftKey: LiftKey
  isActive: boolean
  showQt: boolean
  effectiveYear: number | null
  regionalsQtKg: number | undefined
  nationalsQtKg: number | undefined
}) {
  const RECENT_WINDOW_DAYS = 730
  const [chartView, setChartView] = useState<'recent' | 'full'>('recent')

  const chartData = useMemo(
    () => buildChartData(data, liftKey),
    [data, liftKey],
  )

  const displayedChartData = useMemo(() => {
    if (chartView === 'full') return chartData
    const histDays = chartData
      .filter((r) => r.history != null)
      .map((r) => r.days)
    if (histDays.length === 0) return chartData
    const cutoff = Math.max(...histDays) - RECENT_WINDOW_DAYS
    return chartData.filter(
      (r) => r.days >= cutoff || r.projected != null,
    )
  }, [chartData, chartView])

  const showQtLines = showQt && liftKey === 'total' && effectiveYear != null
  const regionalsQt: number | undefined =
    showQtLines ? regionalsQtKg : undefined
  const nationalsQt: number | undefined =
    showQtLines ? nationalsQtKg : undefined

  return (
    <div>
      <div className="flex items-center gap-2 mb-2 text-xs">
        <span className="text-zinc-400 uppercase tracking-wide">View</span>
        <div
          role="radiogroup"
          aria-label="Chart time window"
          className="inline-flex bg-zinc-900 border border-zinc-800 rounded overflow-hidden"
        >
          <button
            type="button"
            role="radio"
            aria-checked={chartView === 'recent'}
            onClick={() => setChartView('recent')}
            className={
              'px-3 py-1 transition-colors ' +
              (chartView === 'recent'
                ? 'bg-zinc-800 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-200')
            }
          >
            Recent
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={chartView === 'full'}
            onClick={() => setChartView('full')}
            className={
              'px-3 py-1 border-l border-zinc-800 transition-colors ' +
              (chartView === 'full'
                ? 'bg-zinc-800 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-200')
            }
          >
            Full history
          </button>
        </div>
      </div>

      <div className="h-[400px] sm:h-[480px]">
        {isActive && (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={displayedChartData} margin={{ top: 16, right: 24, bottom: 8, left: 8 }}>
              <CartesianGrid stroke={COLORS.grid} strokeDasharray="3 3" />
              <XAxis
                dataKey="days"
                tick={{ fill: '#a1a1aa', fontSize: 12 }}
                label={{
                  value: 'Days from first meet',
                  position: 'insideBottom',
                  offset: -4,
                  fill: '#71717a',
                  fontSize: 11,
                }}
                type="number"
                domain={['auto', 'auto']}
              />
              <YAxis
                tick={{ fill: '#a1a1aa', fontSize: 12 }}
                label={{
                  value: `${liftLabel(liftKey)} (kg)`,
                  angle: -90,
                  position: 'insideLeft',
                  fill: '#71717a',
                  fontSize: 11,
                }}
                domain={['auto', 'auto']}
              />
              <Tooltip
                content={<ProjectionTooltip liftLabel={liftLabel(liftKey)} />}
              />
              <Legend verticalAlign="top" height={28} wrapperStyle={{ paddingBottom: 4 }} />
              <Area
                type="monotone"
                dataKey="piBand"
                name="95% prediction interval"
                fill={COLORS.piBand}
                fillOpacity={0.18}
                stroke="none"
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="projected"
                name="Projected"
                stroke={COLORS.projected}
                strokeWidth={2}
                strokeDasharray="6 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Scatter
                dataKey="history"
                name="Actual meets"
                fill={COLORS.history}
                isAnimationActive={false}
              />
              {regionalsQt != null && (
                <ReferenceLine
                  y={regionalsQt}
                  stroke="#94a3b8"
                  strokeDasharray="4 4"
                  ifOverflow="extendDomain"
                  label={{
                    value: `Regionals ${effectiveYear ?? ''} (${regionalsQt.toFixed(0)})`.trim(),
                    position: 'insideTopLeft',
                    fill: '#94a3b8',
                    fontSize: 11,
                    offset: 6,
                  }}
                />
              )}
              {nationalsQt != null && (
                <ReferenceLine
                  y={nationalsQt}
                  stroke="#FB923C"
                  strokeDasharray="4 4"
                  ifOverflow="extendDomain"
                  label={{
                    value: `Nationals ${effectiveYear ?? ''} (${nationalsQt.toFixed(0)})`.trim(),
                    position: 'insideTopLeft',
                    fill: '#FB923C',
                    fontSize: 11,
                    offset: 6,
                  }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

export { ProjectionChart, buildChartData, COLORS }
export type { ChartRow, LiftKey }
