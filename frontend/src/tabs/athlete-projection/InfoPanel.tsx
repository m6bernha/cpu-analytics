import { type AthleteProjectionResponse, type AthleteProjectionLift } from '../../lib/api'

type LiftKey = 'total' | 'squat' | 'bench' | 'deadlift'

function InfoPanel({
  data,
  liftKey,
  showQt,
  effectiveYear,
  regionalsQt,
  nationalsQt,
}: {
  data: AthleteProjectionResponse
  liftKey: LiftKey
  showQt: boolean
  effectiveYear: number | null
  regionalsQt: number | undefined
  nationalsQt: number | undefined
}) {
  const bracket = data.meta?.lifter_bracket
  const liftRow = liftKey === 'total' ? null : data.lifts?.[liftKey]
  const showProximity =
    showQt && liftKey === 'total' && (regionalsQt != null || nationalsQt != null)

  return (
    <div
      className={
        'mt-4 grid grid-cols-1 gap-3 max-w-4xl mx-auto ' +
        (showProximity ? 'md:grid-cols-4' : 'md:grid-cols-3')
      }
    >
      <InfoCard title="Cohort">
        {bracket ? (
          <>
            <Row label="Age division" value={data.age_division ?? '-'} />
            <Row label="GLP bracket" value={bracket.bracket} />
            <Row label="GLP score" value={bracket.glp_score?.toFixed(1) ?? '-'} />
            <Row
              label="Cohort size"
              value={`${bracket.n_cell} lifter${bracket.n_cell === 1 ? '' : 's'}`}
            />
            {bracket.merged_from.length > 0 && (
              <Row
                label="Merged with"
                value={bracket.merged_from.filter((b) => b !== bracket.bracket).join(', ') || '-'}
              />
            )}
            {bracket.is_global_fallback && (
              <div className="text-xs text-orange-400 mt-1">
                Division has sparse data; using division-global slope.
              </div>
            )}
          </>
        ) : (
          <div className="text-zinc-500 text-xs">Cohort info unavailable.</div>
        )}
      </InfoCard>

      <InfoCard title="Shrinkage">
        {liftRow ? (
          <>
            <Row label="Meets contested" value={String(liftRow.n_meets)} />
            <Row
              label="Personal weight"
              value={`${Math.round(liftRow.w_personal * 100)}%`}
            />
            <Row
              label="Cohort weight"
              value={`${Math.round((1 - liftRow.w_personal) * 100)}%`}
            />
            <Row
              label="Current level"
              value={
                liftRow.current_level != null
                  ? `${liftRow.current_level.toFixed(1)} kg`
                  : '-'
              }
            />
            <Row
              label="Rate"
              value={
                liftRow.slope_combined_kg_per_month != null
                  ? `${liftRow.slope_combined_kg_per_month.toFixed(2)} kg/mo`
                  : '-'
              }
            />
          </>
        ) : (
          <PerLiftShrinkageSummary data={data} />
        )}
      </InfoCard>

      <InfoCard title="Uncertainty">
        <Row
          label="K-M multiplier"
          value={data.meta?.km_multiplier.toFixed(2) ?? '-'}
        />
        <Row
          label="K-M sample"
          value={
            data.meta?.km_sample_size != null
              ? `${data.meta.km_sample_size} lifters`
              : '-'
          }
        />
        <Row
          label="Bracket transitions"
          value={String(data.meta?.bracket_transitions ?? 0)}
        />
        <Row
          label="As of"
          value={data.as_of_date ?? '-'}
        />
      </InfoCard>

      {showProximity && (
        <InfoCard title={`QT proximity (${effectiveYear ?? ''})`.trim()}>
          <QtProximityRows
            data={data}
            regionalsQt={regionalsQt}
            nationalsQt={nationalsQt}
          />
        </InfoCard>
      )}
    </div>
  )
}

function QtProximityRows({
  data,
  regionalsQt,
  nationalsQt,
}: {
  data: AthleteProjectionResponse
  regionalsQt: number | undefined
  nationalsQt: number | undefined
}) {
  const current = currentTotal(data)
  return (
    <>
      <Row
        label="Current total"
        value={current != null ? `${current.toFixed(1)} kg` : '-'}
      />
      {regionalsQt != null && (
        <QtGapRow label="Regionals" current={current} qt={regionalsQt} data={data} />
      )}
      {nationalsQt != null && (
        <QtGapRow label="Nationals" current={current} qt={nationalsQt} data={data} />
      )}
    </>
  )
}

function QtGapRow({
  label,
  current,
  qt,
  data,
}: {
  label: string
  current: number | null
  qt: number
  data: AthleteProjectionResponse
}) {
  if (current == null) {
    return <Row label={label} value="-" />
  }
  if (current >= qt) {
    return (
      <Row
        label={label}
        value={`+${(current - qt).toFixed(1)} kg above`}
        valueClass="text-emerald-400"
      />
    )
  }
  const gap = qt - current
  const crossingMonth = monthsToReach(data, qt)
  const timing =
    crossingMonth == null
      ? `beyond ${data.horizon_months ?? 12} mo horizon`
      : `~${crossingMonth.toFixed(1)} mo`
  return (
    <Row
      label={label}
      value={`-${gap.toFixed(1)} kg (${timing})`}
      valueClass={crossingMonth == null ? 'text-orange-400' : 'text-zinc-200'}
    />
  )
}

function currentTotal(data: AthleteProjectionResponse): number | null {
  const hist = data.total_history ?? []
  if (hist.length === 0) return null
  return hist[hist.length - 1].total_kg
}

function monthsToReach(
  data: AthleteProjectionResponse,
  target: number,
): number | null {
  const pts = data.total_projected_points ?? []
  if (pts.length === 0) return null
  const current = currentTotal(data)
  let prevKg = current ?? pts[0].projected_kg
  let prevMonth = 0
  for (const p of pts) {
    if (p.projected_kg >= target) {
      if (p.projected_kg === prevKg) return p.months_from_last
      const frac = (target - prevKg) / (p.projected_kg - prevKg)
      return prevMonth + frac * (p.months_from_last - prevMonth)
    }
    prevKg = p.projected_kg
    prevMonth = p.months_from_last
  }
  return null
}

function PerLiftShrinkageSummary({ data }: { data: AthleteProjectionResponse }) {
  if (!data.lifts) return <div className="text-zinc-500 text-xs">-</div>
  return (
    <div className="space-y-1.5 text-xs">
      {(['squat', 'bench', 'deadlift'] as const).map((k) => {
        const l = data.lifts![k] as AthleteProjectionLift
        return (
          <div key={k} className="flex justify-between gap-4">
            <span className="text-zinc-400 capitalize">{k}</span>
            <span className="text-zinc-200">
              n={l.n_meets} · w<sub>p</sub>={Math.round(l.w_personal * 100)}%
              {l.slope_combined_kg_per_month != null && (
                <> · {l.slope_combined_kg_per_month.toFixed(2)} kg/mo</>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function InfoCard({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="p-3 bg-zinc-900/40 border border-zinc-800 rounded">
      <div className="text-zinc-300 text-xs uppercase tracking-wide mb-2">
        {title}
      </div>
      <div className="space-y-1">{children}</div>
    </div>
  )
}

function Row({
  label,
  value,
  valueClass,
}: {
  label: string
  value: string
  valueClass?: string
}) {
  return (
    <div className="flex justify-between text-xs gap-2">
      <span className="text-zinc-400">{label}</span>
      <span className={`font-medium ${valueClass ?? 'text-zinc-200'}`}>
        {value}
      </span>
    </div>
  )
}

export { InfoPanel }
export type { LiftKey }
