// About page -- global methodology and disclaimers.
//
// Linked from the methodology <details> block on every other tab. The
// plateau-model comparison section renders the live MAPE numbers from
// data/backtest_results.json (mirrored into frontend/src/data/ by
// data/backtest_projection.py on every --output write).

import backtestResults from '../data/backtest_results.json'

type EngineKey = 'engine_c' | 'log_linear' | 'gompertz'

interface EngineSummary {
  engine: EngineKey
  lifter_count: number
  mape_by_horizon: Record<string, number>
  sample_sizes_by_horizon: Record<string, number>
}

interface BacktestArtifact {
  inputs: {
    parquet: string
    min_meets: number
    holdout: number
    horizons_months: number[]
  }
  summary: {
    engines: EngineSummary[]
    processed_lifters: number
  }
  ship_gate: {
    engine_c_mape_6mo_limit: number
    engine_c_mape_12mo_limit: number
    log_linear_margin_12mo_limit_pp: number
  }
}

const ENGINE_LABEL: Record<EngineKey, string> = {
  engine_c: 'Engine C (GLP-bracket shrinkage)',
  log_linear: 'Log-linear in time',
  gompertz: 'Gompertz',
}

export default function About({ isActive: _isActive }: { isActive: boolean }) {
  return (
    <article className="max-w-3xl text-zinc-300 text-sm leading-relaxed">
      <header className="mb-8">
        <h2 className="text-zinc-100 text-xl font-semibold mb-1">About</h2>
        <p className="text-zinc-500 text-sm">
          Methodology and disclaimers for cpu-analytics, with emphasis on
          the Athlete Projection BETA tab. Short methodology notes on each
          user-facing tab link here for the full version.
        </p>
      </header>

      <Section title="What this site does">
        <p>
          cpu-analytics is a public web app for Canadian raw powerlifters
          competing in CPU- and IPF-sanctioned meets. It aggregates every
          CPU meet in the OpenIPF bulk export and surfaces three views:
          cohort progression over time, QT qualifying-total coverage, and
          an individual lifter lookup. The Athlete Projection BETA tab
          extends the lookup with a per-lift forward projection.
        </p>
      </Section>

      <Section title="What this site does NOT do">
        <ul className="list-disc list-inside space-y-1 text-zinc-400">
          <li>Model weight-class changes or raw-to-equipped transitions.</li>
          <li>Predict injuries, comeback arcs, or retirements.</li>
          <li>Forecast your meet-day performance on a specific date.</li>
          <li>Infer training quality, coaching, or life stress.</li>
          <li>Serve as a coach. Projections are cohort baselines, not prescriptions.</li>
        </ul>
      </Section>

      <Section title="Data source">
        <p>
          OpenPowerlifting OpenIPF bulk export, CC0. Refreshed weekly via
          a GitHub Actions cron that downloads the latest CSV, filters to{' '}
          <code className="text-zinc-200">Country=Canada</code> and{' '}
          <code className="text-zinc-200">ParentFederation=IPF</code>, and
          republishes as a parquet in a rolling GitHub Release. The
          production backend downloads that parquet on cold start. Live
          CPU QT standards are scraped from powerlifting.ca on the same
          weekly cadence for the QT Squeeze tab.
        </p>
      </Section>

      <Section title="Engine C (Simple): Bayesian shrinkage">
        <p>
          Engine C is the default projection engine. It combines a
          lifter&apos;s own trajectory with a cohort slope drawn from a 2D
          matrix of (age division) times (IPF GL Points bracket).
        </p>
        <h4 className="text-zinc-200 font-medium mt-3 mb-1">Per-lift math</h4>
        <p>
          Each of Squat, Bench, Deadlift is fitted independently:
        </p>
        <ul className="list-disc list-inside space-y-1 text-zinc-400 ml-2">
          <li>
            <span className="text-zinc-300">Personal slope:</span>{' '}
            Huber-robust regression (statsmodels RLM with HuberT norm) on
            the lifter&apos;s meets. Polyfit fallback on convergence failure.
          </li>
          <li>
            <span className="text-zinc-300">Cohort slope:</span>{' '}
            mean Huber slope of lifters in the same (age division, GLP
            bracket) cell.
          </li>
          <li>
            <span className="text-zinc-300">Combined slope:</span>{' '}
            w<sub>p</sub> = n / (n + 5) where n is meets CONTESTING this
            lift. Combined slope = w<sub>p</sub> · personal + (1 &minus;
            w<sub>p</sub>) · cohort. A bench-only meet counts toward{' '}
            n<sub>bench</sub>, not n<sub>squat</sub> or n<sub>deadlift</sub>.
          </li>
          <li>
            <span className="text-zinc-300">Current level:</span>{' '}
            max of the lifter&apos;s last 3 totals contesting that lift (median
            of last 2 if fewer than 3). Level is NOT shrunk. Only the slope
            is shrunk.
          </li>
          <li>
            <span className="text-zinc-300">Combine to total:</span>{' '}
            the three per-lift projections are summed at each horizon point
            with prediction-interval variance added in quadrature.
          </li>
        </ul>

        <h4 className="text-zinc-200 font-medium mt-3 mb-1">Prediction interval</h4>
        <p>
          PI half-width at horizon t = z<sub>95</sub> · sqrt(
          w<sub>p</sub>² · sigma<sub>personal</sub>² · (1 + 1/n + (t &minus; t̄)² / S<sub>xx</sub>)
          + (1 &minus; w<sub>p</sub>)² · (sigma<sub>cohort-slope</sub> · k<sub>KM</sub> · t<sub>offset</sub>)²
          ). Widens quadratically. The cohort term is inflated by a
          Kaplan-Meier dropout multiplier.
        </p>
      </Section>

      <Section title="Engine D (Advanced): mixed-effects">
        <p>
          Engine D fits a statsmodels MixedLM per lift with a random
          intercept and random slope per lifter, plus fixed effects for
          age division and IPF GL bracket. Prediction intervals come
          directly from the posterior predictive distribution.
        </p>
        <p className="text-zinc-400 mt-2">
          Advanced is currently a placeholder that delegates to Simple
          while the MixedLM wiring and convergence probe ship in a
          follow-up release. When the probe detects convergence failure
          on more than 10 percent of backtest lifters, the toggle stays
          hidden.
        </p>
      </Section>

      <Section title="GLP-bracket cohort stratification">
        <p>
          Plateau handling uses a 2D cohort matrix, one cell per (age
          division, IPF GL Points bracket, lift) combination. Elite lifters
          progress slower; this approach captures the plateau structure
          explicitly rather than fitting a continuous slope-vs-level
          function. Approach follows coach Sean Yen&apos;s input.
        </p>

        <h4 className="text-zinc-200 font-medium mt-3 mb-1">Bracket boundaries</h4>
        <p className="text-zinc-400">
          GLP &lt; 60, 60-70, 70-80, 80-90, 90-95, 95-100, 100-105, 105-110,
          110-115, 115-120, &gt;= 120. Narrower above GLP 90 to resolve
          plateau effects where they matter most.
        </p>

        <h4 className="text-zinc-200 font-medium mt-3 mb-1">Why IPF GL?</h4>
        <p>
          Raw TotalKg is weight-class dependent. A 500 kg total at 59 kg
          BW and at 120+ kg BW are not comparable. Competition attendance
          is a participation signal, not an ability signal. IPF GL Points
          normalizes across bodyweight and sex so the cohort reflects
          lifters of comparable ability. Raw SBD coefficients only for
          v1; equipped is out of scope.
        </p>

        <h4 className="text-zinc-200 font-medium mt-3 mb-1">Minimum cell size</h4>
        <p>
          Every cell needs at least 20 lifters to publish an independent
          slope. Sparse cells merge upward with the next bracket, then
          downward if still below the threshold. Every merge is logged at
          precompute time and exposed in the API response as{' '}
          <code className="text-zinc-200">merged_from</code>. When the
          entire age division has fewer than 20 lifters across ALL
          brackets for a given lift, a division-global slope is used as
          a floor.
        </p>

        <h4 className="text-zinc-200 font-medium mt-3 mb-1">Bracket transitions</h4>
        <p>
          Projection is a two-pass calculation. Pass 1 uses the lifter&apos;s
          starting bracket for all horizon points. If the pass-1 total
          crosses a bracket boundary during the horizon, pass 2 rebuilds
          each lift&apos;s projection with the bracket-specific cohort slope
          for each segment. Personal slope is constant across segments;
          only the cohort contribution changes. Boundary-crossing points
          may show a small discontinuity. No smoothing in v1.
        </p>
      </Section>

      <Section title="Plateau-model comparison (backtest)">
        <p>
          The GLP-bracket approach is benchmarked against log-linear-in-time
          and Gompertz fits using a walk-forward backtest on lifters with
          15+ career meets. Mean absolute percentage error at 3, 6, 12, and
          18 months is the comparison metric. Ship thresholds: if GLP-bracket
          loses by more than 2 percentage points at the 12-month horizon,
          swap to the winner. If MAPE exceeds 6 percent at 6 months or 12
          percent at 12 months for Engine C, escalate.
        </p>

        <BacktestTable artifact={backtestResults as BacktestArtifact} />
      </Section>

      <Section title="Kaplan-Meier dropout correction">
        <p>
          The cohort slope is calibrated on lifters who kept competing. A
          lifter is treated as a Kaplan-Meier dropout if and only if their
          most recent recorded meet is more than 18 months before the
          dataset refresh date. Historical gaps of 18+ months are NOT
          dropouts as long as the lifter returned and has recent activity
          within 18 months. The 18-month threshold was chosen to absorb
          injury layoffs, life events, and pandemic-style disruptions
          while still catching genuine retirees.
        </p>
        <p>
          At projection time, the cohort contribution to the prediction
          interval is inflated by 1 / sqrt(S(h)), where S(h) is the
          Kaplan-Meier survival probability at the horizon. Clamped to
          [1.0, 3.0] so pathological survival estimates cannot collapse or
          explode the band.
        </p>
      </Section>

      <Section title="Per-lift separation">
        <p>
          Squat, Bench, and Deadlift are projected independently and
          summed. A bombed squat does not compress the bench slope. An
          injury that affects only one lift stays localized. Per-lift
          n counts only meets that actually contested that lift.
        </p>
      </Section>

      <Section title="Prediction vs confidence intervals">
        <p>
          The shaded band on the chart is a 95 percent prediction
          interval for this specific lifter&apos;s next meet total at the
          given horizon. It is NOT a confidence interval for the fit. A
          confidence interval would ask where the true slope lives given
          infinite observations of this lifter&apos;s meets. A prediction
          interval asks where THIS lifter&apos;s next meet realisation is
          likely to land, a harder question that includes both fit
          uncertainty and meet-to-meet variance.
        </p>
      </Section>

      <Section title="Age-division cohorts (no cross-pool)">
        <p>
          Cohorts are partitioned by age division: Sub-Junior, Junior,
          Open (24-39), Master 1, Master 2, Master 3, Master 4. Slopes
          are fit independently per division. A 30-year-old does not
          borrow from the Master 3 slope. Open is 24 through 39
          inclusive.
        </p>
      </Section>

      <Section title="Horizon caps">
        <p>
          Hard cap 18 months in the UI. Loud warning past 12 months.
          Lifters with fewer than 5 meets are clamped server-side to 6
          months because the personal slope is unstable there. Projections
          past 24 months never render.
        </p>
      </Section>

      <Section title="Outlier flag">
        <p>
          If a lifter&apos;s most recent meet is more than 2.5 sigma below
          their Huber fit on any lift, a warning surfaces on the tab. The
          projection still uses the max-of-last-3 convention for current
          level, so one bombed meet does not collapse the trajectory, but
          the flag lets you know one anomaly is present.
        </p>
      </Section>

      <Section title="BETA exit criteria">
        <p>
          BETA exit criteria are intentionally deferred. Once the tab has
          meaningful production exposure and real-world feedback surfaces
          specific failure modes, this section will be updated with
          concrete graduation criteria. Until then, treat projections as
          directional.
        </p>
      </Section>

      <Section title="UX revisit">
        <p>
          The Simple / Advanced toggle for engines C and D is an
          approximation of a design question we have not yet answered.
          After release, the alternatives (overlaid, side-by-side, or a
          pick-one default with an advanced-mode escape hatch) will be
          evaluated against real usage.
        </p>
      </Section>

      <Section title="References">
        <ul className="list-disc list-inside space-y-1 text-zinc-400 text-xs">
          <li>
            Efron, B., and Morris, C. (1975). &ldquo;Data Analysis Using
            Stein&apos;s Estimator and Its Generalizations.&rdquo;{' '}
            <em>JASA</em>.
          </li>
          <li>
            Gelman et al., <em>Bayesian Data Analysis</em>, 3rd ed.,
            Chapter 5 on hierarchical models.
          </li>
          <li>
            Berthelot, G., et al. (2019). &ldquo;An Integrative Modeling
            Approach to the Age-Performance Relationship in Mammals at the
            Cellular Scale.&rdquo; <em>Aging</em>.
          </li>
          <li>
            Huebner, M. and Perperoglou, A. on strength-sport progression
            patterns.
          </li>
          <li>
            OpenPowerlifting methodology documentation at{' '}
            <a
              href="https://www.openpowerlifting.org"
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2 hover:text-zinc-300"
            >
              openpowerlifting.org
            </a>.
          </li>
          <li>
            Kaplan, E. L. and Meier, P. (1958). &ldquo;Nonparametric
            Estimation from Incomplete Observations.&rdquo; <em>JASA</em>.
          </li>
        </ul>
      </Section>

      <Section title="Acknowledgements">
        <p>
          Cohort stratification by IPF GL Points bracket follows coach
          Sean Yen&apos;s guidance. Methodology roundtable feedback from the
          CPU community shaped the horizon caps, outlier-flag threshold,
          and survivorship caveats.
        </p>
      </Section>
    </article>
  )
}

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-6">
      <h3 className="text-zinc-100 text-base font-semibold mb-2">{title}</h3>
      <div className="space-y-2">{children}</div>
    </section>
  )
}

function BacktestTable({ artifact }: { artifact: BacktestArtifact }) {
  const horizons = artifact.inputs.horizons_months
  const engines = artifact.summary.engines
  const engineC = engines.find((e) => e.engine === 'engine_c')
  const logLinear = engines.find((e) => e.engine === 'log_linear')
  const gompertz = engines.find((e) => e.engine === 'gompertz')
  const gates = artifact.ship_gate

  const engineCMape6 = engineC?.mape_by_horizon['6']
  const engineCMape12 = engineC?.mape_by_horizon['12']
  const logLinearMape12 = logLinear?.mape_by_horizon['12']
  const gompertzMape12 = gompertz?.mape_by_horizon['12']

  const gate6mo =
    engineCMape6 == null
      ? null
      : engineCMape6 <= gates.engine_c_mape_6mo_limit
  const gate12mo =
    engineCMape12 == null
      ? null
      : engineCMape12 <= gates.engine_c_mape_12mo_limit
  const bestAlt12mo = (() => {
    const alts: number[] = []
    if (logLinearMape12 != null) alts.push(logLinearMape12)
    if (gompertzMape12 != null) alts.push(gompertzMape12)
    return alts.length ? Math.min(...alts) : null
  })()
  const gateMargin =
    engineCMape12 == null || bestAlt12mo == null
      ? null
      : engineCMape12 - bestAlt12mo <= gates.log_linear_margin_12mo_limit_pp

  return (
    <div className="mt-3 space-y-3">
      <div className="overflow-x-auto">
        <table className="text-xs w-full border-collapse">
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="text-left font-medium py-1.5 pr-3">Engine</th>
              {horizons.map((h) => (
                <th key={h} className="text-right font-medium py-1.5 px-2">
                  {h} mo
                </th>
              ))}
              <th className="text-right font-medium py-1.5 pl-2">Lifters</th>
            </tr>
          </thead>
          <tbody>
            {engines.map((e) => (
              <tr
                key={e.engine}
                className="border-b border-zinc-800 text-zinc-300"
              >
                <td className="py-1.5 pr-3">
                  <span
                    className={
                      e.engine === 'engine_c' ? 'text-zinc-100 font-medium' : ''
                    }
                  >
                    {ENGINE_LABEL[e.engine]}
                  </span>
                </td>
                {horizons.map((h) => {
                  const key = String(h)
                  const mape = e.mape_by_horizon[key]
                  const n = e.sample_sizes_by_horizon[key]
                  return (
                    <td
                      key={h}
                      className="text-right py-1.5 px-2 tabular-nums"
                    >
                      {mape != null ? `${mape.toFixed(2)}%` : '\u2014'}
                      {n != null && (
                        <span className="text-zinc-500 ml-1">
                          (n={n})
                        </span>
                      )}
                    </td>
                  )
                })}
                <td className="text-right py-1.5 pl-2 text-zinc-400 tabular-nums">
                  {e.lifter_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-zinc-500 text-xs space-y-1">
        <p>
          {artifact.summary.processed_lifters} lifters, holdout last{' '}
          {artifact.inputs.holdout} meets, minimum{' '}
          {artifact.inputs.min_meets} career meets. Per-horizon{' '}
          <code className="text-zinc-400">n</code> is the subset of lifters
          whose held-out meets include one at that horizon (within a
          tolerance window).
        </p>
        <p>
          Baseline is a 50-lifter Canada+IPF smoke sample. A full-OpenIPF
          run is a one-off manual step once the 285 MB bulk CSV is available
          locally (see{' '}
          <code className="text-zinc-400">data/backtest_projection.py</code>{' '}
          docstring).
        </p>
      </div>

      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
        <h4 className="text-zinc-200 text-xs font-medium mb-2">
          Ship gates
        </h4>
        <ul className="space-y-1 text-xs">
          <Gate
            pass={gate6mo}
            label={
              <>
                Engine C MAPE at 6 months &le;{' '}
                {gates.engine_c_mape_6mo_limit.toFixed(1)}%
              </>
            }
            value={
              engineCMape6 != null
                ? `${engineCMape6.toFixed(2)}%`
                : 'unavailable'
            }
          />
          <Gate
            pass={gate12mo}
            label={
              <>
                Engine C MAPE at 12 months &le;{' '}
                {gates.engine_c_mape_12mo_limit.toFixed(1)}%
              </>
            }
            value={
              engineCMape12 != null
                ? `${engineCMape12.toFixed(2)}%`
                : 'unavailable'
            }
          />
          <Gate
            pass={gateMargin}
            label={
              <>
                Engine C does not lose by more than{' '}
                {gates.log_linear_margin_12mo_limit_pp.toFixed(1)} pp to
                best alternative at 12 months
              </>
            }
            value={
              engineCMape12 != null && bestAlt12mo != null
                ? `${(engineCMape12 - bestAlt12mo >= 0 ? '+' : '') + (engineCMape12 - bestAlt12mo).toFixed(2)} pp`
                : 'unavailable'
            }
          />
        </ul>
      </div>
    </div>
  )
}

function Gate({
  pass,
  label,
  value,
}: {
  pass: boolean | null
  label: React.ReactNode
  value: string
}) {
  const icon =
    pass === null ? (
      <span className="text-zinc-500" aria-label="unavailable">&#x25CB;</span>
    ) : pass ? (
      <span className="text-emerald-400" aria-label="pass">&#x2713;</span>
    ) : (
      <span className="text-rose-400" aria-label="fail">&#x2717;</span>
    )
  return (
    <li className="flex items-start gap-2 text-zinc-400">
      <span className="flex-shrink-0 mt-0.5 w-4 text-center">{icon}</span>
      <span className="flex-1">{label}</span>
      <span className="text-zinc-300 tabular-nums">{value}</span>
    </li>
  )
}
