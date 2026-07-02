function MethodologyBlock() {
  return (
    <details className="mt-8 max-w-3xl">
      <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
        Methodology and caveats
      </summary>
      <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
        <p>
          <span className="text-zinc-400 font-medium">Engine C (Simple):</span>{' '}
          Bayesian shrinkage combines the lifter's own Huber-robust slope with
          a cohort slope from their age division and IPF GL Points bracket.
          Weight on personal history grows with meet count as w<sub>p</sub>{' '}
          = n / (n + 5). Level is never shrunk, only slope.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Engine D (Advanced):</span>{' '}
          Mixed-effects model with random intercept + slope per lifter, fixed
          effects for age division and GLP bracket. Advanced is currently a
          placeholder that delegates to Simple; MixedLM wiring ships in a
          follow-up release.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Prediction interval:</span>{' '}
          Shown band is a 95 percent prediction interval for where this
          specific lifter's next meet total could land, not a confidence
          interval for the fit. It widens quadratically with horizon and is
          inflated by a Kaplan-Meier dropout multiplier on the cohort term.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Horizon caps:</span> 18
          months hard cap. Lifters with fewer than 5 meets are capped at 6
          months. A loud warning fires past 12 months.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">What is not modelled:</span>{' '}
          Weight class changes, raw-to-equipped transitions, injury gaps,
          meet-day performance on specific dates, training quality, or coaching.
          Projection is a cohort baseline, not a prediction of your next result.
        </p>
      </div>
    </details>
  )
}

export default MethodologyBlock
