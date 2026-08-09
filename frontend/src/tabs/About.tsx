// About page -- global methodology and disclaimers.
//
// Linked from the methodology <details> block on every other tab. The
// plateau-model comparison section renders the live MAPE numbers from
// data/backtest_results.json (mirrored into frontend/src/data/ by
// data/backtest_projection.py on every --output write).

import backtestResults from '../data/backtest_results.json'

// Deliberately a plain string rather than a union. The harness derives the
// engine list from the data, so a sweep artifact carries `damped_tau*` keys
// that no union could enumerate, and a union here would be a type that
// lies about what the JSON can contain.
type EngineKey = string

interface HorizonCell {
  mape: number | null
  median_ape: number | null
  bias: number | null
  n: number
  coverage: number | null
}

interface EngineSummary {
  engine: EngineKey
  by_horizon: Record<string, HorizonCell>
}

interface HeadToHeadCell {
  n_paired: number
  n_lifters: number
  mape_baseline: number | null
  mape_challenger: number | null
  mean_diff: number | null
  ci_low: number | null
  ci_high: number | null
  challenger_win_rate: number | null
}

interface HeadToHead {
  challenger: EngineKey
  baseline: EngineKey
  by_horizon: Record<string, HeadToHeadCell>
}

interface BacktestArtifact {
  schema_version: number
  inputs: {
    parquet: string
    min_career_meets: number
    min_train_meets: number
    holdout_span_months: number
    horizons_months: number[]
    bootstrap_resamples: number
    damping_tau_days?: number | null
  }
  summary: {
    engines: EngineSummary[]
    scored_lifters: number
    observations: number
    pool_lifters: number
  }
  head_to_head: HeadToHead[]
  ship_gate: {
    engine_c_bias_12mo_limit_pp: number
    engine_c_bias_18mo_limit_pp: number
    engine_c_mape_6mo_limit: number
    engine_c_mape_12mo_limit: number
    challenger_margin_12mo_limit_pp: number
  }
}

const ENGINE_LABEL: Record<string, string> = {
  engine_c: 'Engine C (GLP-bracket shrinkage)',
  engine_c_undamped: 'Engine C before damping',
  log_linear: 'Log-linear in time',
  gompertz: 'Gompertz',
  flat_last: 'No change from last meet',
  flat_level: "No change from Engine C's starting level",
}

// Short forms for table headers, where the full label does not fit.
const ENGINE_SHORT: Record<string, string> = {
  engine_c: 'Engine C',
  engine_c_undamped: 'Engine C (undamped)',
  log_linear: 'Log-linear',
  gompertz: 'Gompertz',
  flat_last: 'No change',
  flat_level: 'Level only',
}

// A sweep run adds `damped_tau*` engines that have no fixed label. Falling
// back to the raw key keeps the table readable rather than blank, and a
// sweep artifact is never what ships.
function engineLabel(key: string): string {
  return ENGINE_LABEL[key] ?? key
}

function engineShort(key: string): string {
  return ENGINE_SHORT[key] ?? key
}

export default function About({ isActive: _isActive }: { isActive: boolean }) {
  const artifact = backtestResults as unknown as BacktestArtifact
  const damping = artifact.inputs.damping_tau_days ?? null
  return (
    <article className="max-w-3xl text-zinc-300 text-sm leading-relaxed">
      <header className="mb-8">
        <h2 className="text-zinc-100 text-xl font-semibold mb-1">About</h2>
        <p className="text-zinc-400 text-sm">
          Methodology and disclaimers for cpu-analytics, with emphasis on
          the Athlete Projection BETA tab. Short methodology notes on each
          user-facing tab link here for the full version.
        </p>
      </header>

      <Section title="What this site does">
        <p>
          cpu-analytics is a public web app for Canadian raw powerlifters
          competing in CPU- and IPF-sanctioned meets. It aggregates every
          Canadian IPF-affiliated meet in the OpenIPF bulk export and
          surfaces seven views: cohort progression over time, rankings of
          currently active lifters, a per-lift Athlete Projection (BETA),
          an individual lifter lookup, live qualifying-total coverage for
          CPU and all ten provinces, Scout (BETA) for meet scouting
          reports from a pasted roster, and this methodology page.
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
          qualifying totals are scraped on the same weekly cadence for the
          Qualifying Totals tab: CPU standards from powerlifting.ca, plus
          provincial standards from the Ontario, Manitoba, Nova Scotia,
          Newfoundland, Alberta, and Quebec federations. BC and
          Saskatchewan defer to CPU Regional standards, and New Brunswick
          and PEI run open-entry provincials with no qualifying total.
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

      <Section title="Saturating slope: why projections flatten">
        <p>
          Projected gain is not the slope multiplied by elapsed time. It is
          slope · tau · (1 &minus; exp(&minus;t / tau)), so the gain
          approaches a ceiling of slope · tau instead of growing without
          limit. The instantaneous rate at t = 0 is still exactly the fitted
          slope, so the first weeks are unchanged. The further out the
          horizon, the more the line bends toward flat.
          {damping != null && (
            <>
              {' '}The constant in production is tau = {damping} days.
            </>
          )}
        </p>
        <p>
          This was added because the straight-line version was measurably,
          one-directionally wrong. Backtested against real held-out meets it
          projected {' '}
          <span className="text-zinc-200">5.09 percent high</span> at 12
          months and{' '}
          <span className="text-zinc-200">12.06 percent high</span> at 36,
          against a 36-month mean absolute error of 12.72 percent. In other
          words nearly the whole error was overshoot rather than noise. The
          table below carries the before and after.
        </p>
        <p>
          The overshoot was the slope, not the starting level. Holding
          Engine C&apos;s own level flat with no growth at all was the most
          accurate predictor tested, at every horizon. That is also why the
          projection can look pessimistic: the starting level is already the
          sum of your best squat, bench and deadlift from your last three
          meets, which is frequently a total you have not hit in any single
          meet. Growth on top of an optimistic starting point is a harder
          thing to earn than growth on top of your last result.
        </p>
        <p className="text-zinc-400">
          Calibration limitation, stated plainly: the constant is fitted on
          lifters with at least 15 career meets whose training data ends 36
          months before their final meet. That pool contains no true
          novices. A lifter in their first year is on the steepest part of
          the curve and is the case this calibration speaks to least. The
          gate table includes a guard for the shortest-history lifters in
          the pool, but it cannot stand in for data that is not there.
          Full reasoning in{' '}
          <code className="text-zinc-400">docs/adr/0004</code>.
        </p>
      </Section>

      <Section title="Engine D (Advanced): mixed-effects">
        <p>
          Engine D fits a statsmodels MixedLM per (age division, GLP
          bracket, lift) cell with a random intercept per lifter and a
          fixed effect for years since first meet. Fitting runs at
          precompute time. Each converged cell is converted into a virtual
          cohort cell that drops into the same projection math as Engine
          C, so the personal-slope shrinkage and prediction-interval
          structure are shared. The per-meet residual variance from the
          fit provides the cohort noise term.
        </p>
        <p className="text-zinc-400 mt-2">
          Engine D is live in production. A cell needs at least 20 lifters
          and 60 meets to fit. Cells below that floor, and any cell that
          fails to converge, fall back to Engine C for that lift and are
          flagged in the response metadata. The engine toggle on the
          Athlete Projection tab appears when the overall convergence rate
          clears a 70 percent gate. The current production fit converges
          on 100 percent of eligible cells.
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
          Engine C is benchmarked against log-linear-in-time and Gompertz
          fits using a walk-forward backtest. Every career in the pool is
          split at 36 months before its final meet. The engines see only the
          training side and project forward to the exact date of each
          held-out meet, which is then bucketed by how far it sits from the
          last training meet.
        </p>
        <p className="text-zinc-400">
          Two reading instructions matter more than the numbers. First, the
          per-engine table below reports each engine on its OWN sample, and
          those columns are not comparable to each other: Gompertz only
          answers when its curve fit converges, so it declines exactly the
          careers that are hardest to fit. Every cross-engine claim comes
          from the paired tables underneath, computed only on observations
          where both engines answered. Second, the 24 and 36 month rows are
          diagnostic. The app caps projections at 18 months and will keep
          doing so, so those rows exist to show how the engines diverge, not
          to advertise a horizon you can request.
        </p>
        <p className="text-zinc-400">
          Two of the entries are deliberately trivial controls rather than
          candidate engines. &ldquo;No change from last meet&rdquo; predicts
          the lifter&apos;s last training total forever, and &ldquo;no change
          from Engine C&apos;s starting level&rdquo; keeps Engine C&apos;s
          level but removes its slope. A model that projects growth should
          beat both. Where it does not, the honest reading is that the model
          is extrapolating too far, and the pair of controls separates how
          much of that comes from the level definition and how much from the
          slope. See{' '}
          <a
            href="https://github.com/m6bernha/cpu-analytics/blob/main/docs/adr/0004-projection-engine-cascade.md"
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-zinc-300"
          >
            ADR 0004
          </a>{' '}
          for what these numbers led to.
        </p>

        <BacktestTable artifact={artifact} />
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
          months because the personal slope is unstable there. The server
          enforces the same 18-month cap regardless of what a request
          asks for.
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
          As usage accumulates, the alternatives (overlaid, side-by-side, or a
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

function fmtPct(value: number | null | undefined, digits = 2): string {
  return value == null ? '\u2014' : `${value.toFixed(digits)}%`
}

function BacktestTable({ artifact }: { artifact: BacktestArtifact }) {
  const horizons = artifact.inputs.horizons_months
  const engines = artifact.summary.engines
  const gates = artifact.ship_gate

  const engineC = engines.find((e) => e.engine === 'engine_c')
  const engineCMape6 = engineC?.by_horizon['6']?.mape ?? null
  const engineCMape12 = engineC?.by_horizon['12']?.mape ?? null
  const engineCBias12 = engineC?.by_horizon['12']?.bias ?? null
  const engineCBias18 = engineC?.by_horizon['18']?.bias ?? null

  const gateBias12 =
    engineCBias12 == null
      ? null
      : Math.abs(engineCBias12) <= gates.engine_c_bias_12mo_limit_pp
  const gateBias18 =
    engineCBias18 == null
      ? null
      : Math.abs(engineCBias18) <= gates.engine_c_bias_18mo_limit_pp

  // The margin gate reads the PAIRED difference, not the gap between two
  // own-sample MAPEs. mean_diff is (challenger - baseline), so the most
  // negative value is Engine C's worst loss. Comparisons whose baseline is
  // NOT Engine C (the Gompertz vs no-change control) must be excluded, or
  // a result that says nothing about Engine C would drive its gate.
  const worstPairedDiff12 = artifact.head_to_head
    .filter((h2h) => h2h.baseline === 'engine_c')
    .reduce<number | null>((worst, h2h) => {
      const diff = h2h.by_horizon['12']?.mean_diff
      if (diff == null) return worst
      return worst == null || diff < worst ? diff : worst
    }, null)

  const gate6mo =
    engineCMape6 == null ? null : engineCMape6 <= gates.engine_c_mape_6mo_limit
  const gate12mo =
    engineCMape12 == null ? null : engineCMape12 <= gates.engine_c_mape_12mo_limit
  const gateMargin =
    worstPairedDiff12 == null
      ? null
      : -worstPairedDiff12 <= gates.challenger_margin_12mo_limit_pp

  return (
    <div className="mt-3 space-y-4">
      <div className="overflow-x-auto">
        <table className="text-xs w-full border-collapse">
          <caption className="text-left text-zinc-400 text-xs pb-1.5">
            MAPE by engine, each on its own sample. Not comparable across rows.
          </caption>
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="text-left font-medium py-1.5 pr-3">Engine</th>
              {horizons.map((h) => (
                <th key={h} className="text-right font-medium py-1.5 px-2">
                  {h} mo
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {engines.map((e) => (
              <tr key={e.engine} className="border-b border-zinc-800 text-zinc-300">
                <td className="py-1.5 pr-3">
                  <span
                    className={
                      e.engine === 'engine_c' ? 'text-zinc-100 font-medium' : ''
                    }
                  >
                    {engineLabel(e.engine)}
                  </span>
                </td>
                {horizons.map((h) => {
                  const cell = e.by_horizon[String(h)]
                  return (
                    <td key={h} className="text-right py-1.5 px-2 tabular-nums">
                      {fmtPct(cell?.mape)}
                      {cell != null && (
                        <span className="text-zinc-400 ml-1">(n={cell.n})</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="overflow-x-auto">
        <table className="text-xs w-full border-collapse">
          <caption className="text-left text-zinc-400 text-xs pb-1.5">
            Signed bias. Positive means the engine projected above what the
            lifter actually totalled.
          </caption>
          <thead>
            <tr className="border-b border-zinc-700 text-zinc-400">
              <th className="text-left font-medium py-1.5 pr-3">Engine</th>
              {horizons.map((h) => (
                <th key={h} className="text-right font-medium py-1.5 px-2">
                  {h} mo
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {engines.map((e) => (
              <tr key={e.engine} className="border-b border-zinc-800 text-zinc-300">
                <td className="py-1.5 pr-3">
                  <span
                    className={
                      e.engine === 'engine_c' ? 'text-zinc-100 font-medium' : ''
                    }
                  >
                    {engineLabel(e.engine)}
                  </span>
                </td>
                {horizons.map((h) => {
                  const bias = e.by_horizon[String(h)]?.bias
                  return (
                    <td key={h} className="text-right py-1.5 px-2 tabular-nums">
                      {bias == null
                        ? '\u2014'
                        : `${bias > 0 ? '+' : ''}${bias.toFixed(2)}%`}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Key on challenger AND baseline. Gompertz appears twice, once
          against Engine C and once against the no-change control, so
          keying on the challenger alone collides and React may drop or
          duplicate a table. */}
      {artifact.head_to_head.map((h2h) => (
        <PairedTable
          key={`${h2h.challenger}-vs-${h2h.baseline}`}
          h2h={h2h}
          horizons={horizons}
        />
      ))}

      <div className="text-zinc-400 text-xs space-y-1">
        <p>
          Pool: {artifact.summary.pool_lifters} lifters with at least{' '}
          {artifact.inputs.min_career_meets} career meets, of which{' '}
          {artifact.summary.scored_lifters} survived the split with at least{' '}
          {artifact.inputs.min_train_meets} training meets and a held-out meet
          in some horizon bucket, giving {artifact.summary.observations}{' '}
          scored observations. Confidence intervals are bootstrap percentile
          intervals over {artifact.inputs.bootstrap_resamples} resamples,
          drawn by lifter rather than by observation, because one lifter
          contributes several correlated observations.
        </p>
        <p>
          Numbers come from a run over the global OpenIPF export, not just
          the Canadian subset, to maximise sample size. Engine C runs through{' '}
          <code className="text-zinc-400">project_from_history</code>, the
          same function the API calls, so the measured engine is the shipped
          engine. Cohort cells are fit on training meets only.
        </p>
        <p>
          Known limitation: the longest buckets are enriched for meets late
          in a career, since holding out the final 36 months is what makes a
          36-month reading possible at all. A lifter who stopped competing
          after a poor meet is over-represented there relative to the
          3-month bucket.
        </p>
      </div>

      <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3">
        <h4 className="text-zinc-200 text-xs font-medium mb-2">Ship gates</h4>
        <p className="text-zinc-400 text-xs mb-2">
          Bias gates lead because the earlier gate set was all MAPE
          thresholds, and every one of them passed on an engine running 5 to
          6 percent high at both horizons the app serves. A threshold on the
          size of an error cannot see the direction of it.
        </p>
        <ul className="space-y-1 text-xs">
          <Gate
            pass={gateBias12}
            label={
              <>
                Engine C bias at 12 months within &plusmn;
                {gates.engine_c_bias_12mo_limit_pp.toFixed(1)} pp
              </>
            }
            value={
              engineCBias12 == null
                ? 'unavailable'
                : `${engineCBias12 > 0 ? '+' : ''}${engineCBias12.toFixed(2)} pp`
            }
          />
          <Gate
            pass={gateBias18}
            label={
              <>
                Engine C bias at 18 months within &plusmn;
                {gates.engine_c_bias_18mo_limit_pp.toFixed(1)} pp
              </>
            }
            value={
              engineCBias18 == null
                ? 'unavailable'
                : `${engineCBias18 > 0 ? '+' : ''}${engineCBias18.toFixed(2)} pp`
            }
          />
          <Gate
            pass={gate6mo}
            label={
              <>
                Engine C MAPE at 6 months &le;{' '}
                {gates.engine_c_mape_6mo_limit.toFixed(1)}%
              </>
            }
            value={fmtPct(engineCMape6)}
          />
          <Gate
            pass={gate12mo}
            label={
              <>
                Engine C MAPE at 12 months &le;{' '}
                {gates.engine_c_mape_12mo_limit.toFixed(1)}%
              </>
            }
            value={fmtPct(engineCMape12)}
          />
          <Gate
            pass={gateMargin}
            label={
              <>
                Engine C does not lose by more than{' '}
                {gates.challenger_margin_12mo_limit_pp.toFixed(1)} pp to any
                challenger at 12 months, paired
              </>
            }
            value={
              worstPairedDiff12 == null
                ? 'unavailable'
                : `${worstPairedDiff12 > 0 ? '+' : ''}${worstPairedDiff12.toFixed(2)} pp`
            }
          />
        </ul>
      </div>
    </div>
  )
}

function PairedTable({
  h2h,
  horizons,
}: {
  h2h: HeadToHead
  horizons: number[]
}) {
  return (
    <div className="overflow-x-auto">
      <table className="text-xs w-full border-collapse">
        <caption className="text-left text-zinc-400 text-xs pb-1.5">
          {engineLabel(h2h.challenger)} against{' '}
          {engineLabel(h2h.baseline)}, paired. Negative means the challenger
          was closer.
        </caption>
        <thead>
          <tr className="border-b border-zinc-700 text-zinc-400">
            <th className="text-left font-medium py-1.5 pr-3">Horizon</th>
            <th className="text-right font-medium py-1.5 px-2">Paired n</th>
            <th className="text-right font-medium py-1.5 px-2">
              {engineShort(h2h.baseline)}
            </th>
            <th className="text-right font-medium py-1.5 px-2">
              {engineShort(h2h.challenger)}
            </th>
            <th className="text-right font-medium py-1.5 px-2">Difference</th>
            <th className="text-right font-medium py-1.5 px-2">95% CI</th>
            <th className="text-right font-medium py-1.5 pl-2">Win rate</th>
          </tr>
        </thead>
        <tbody>
          {horizons.map((h) => {
            const cell = h2h.by_horizon[String(h)]
            const decisive =
              cell?.ci_low != null &&
              cell?.ci_high != null &&
              (cell.ci_high < 0 || cell.ci_low > 0)
            return (
              <tr key={h} className="border-b border-zinc-800 text-zinc-300">
                <td className="py-1.5 pr-3 tabular-nums">{h} mo</td>
                <td className="text-right py-1.5 px-2 tabular-nums text-zinc-400">
                  {cell?.n_paired ?? 0}
                </td>
                <td className="text-right py-1.5 px-2 tabular-nums">
                  {fmtPct(cell?.mape_baseline)}
                </td>
                <td className="text-right py-1.5 px-2 tabular-nums">
                  {fmtPct(cell?.mape_challenger)}
                </td>
                <td
                  className={
                    'text-right py-1.5 px-2 tabular-nums' +
                    (decisive ? ' text-zinc-100 font-medium' : '')
                  }
                >
                  {cell?.mean_diff == null
                    ? '\u2014'
                    : `${cell.mean_diff > 0 ? '+' : ''}${cell.mean_diff.toFixed(2)} pp`}
                </td>
                <td className="text-right py-1.5 px-2 tabular-nums text-zinc-400">
                  {cell?.ci_low == null || cell?.ci_high == null
                    ? '\u2014'
                    : `${cell.ci_low > 0 ? '+' : ''}${cell.ci_low.toFixed(2)} to ${cell.ci_high > 0 ? '+' : ''}${cell.ci_high.toFixed(2)}`}
                </td>
                <td className="text-right py-1.5 pl-2 tabular-nums text-zinc-400">
                  {cell?.challenger_win_rate == null
                    ? '\u2014'
                    : `${(cell.challenger_win_rate * 100).toFixed(0)}%`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
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
      <span className="text-zinc-400" aria-label="unavailable">&#x25CB;</span>
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
