function MethodologyBlock() {
  return (
    <details className="mt-8 max-w-3xl">
      <summary className="text-zinc-400 text-xs cursor-pointer hover:text-zinc-300">
        Methodology and caveats
      </summary>
      <div className="text-zinc-400 text-xs mt-2 space-y-1.5">
        <p>
          <span className="text-zinc-400 font-medium">Engine C (Simple):</span>{' '}
          Bayesian shrinkage combines the lifter's own Huber-robust slope with
          a cohort slope from their age division and IPF GL Points bracket.
          Weight on personal history grows with meet count as w<sub>p</sub>{' '}
          = n / (n + 5). Level is never shrunk, only slope.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">Engine D (Advanced):</span>{' '}
          Mixed-effects model with a random intercept per lifter and a fixed
          effect for years since first meet, fitted per age division and GLP
          bracket cell. Cells that fail to converge, or that fall below 20
          lifters and 60 meets, fall back to Simple for that lift.
        </p>
        <p>
          <span className="text-zinc-400 font-medium">
            Why the line flattens:
          </span>{' '}
          Two things hold it down, and both are deliberate. The starting
          point is your best squat, bench and deadlift from your last three
          meets, added together, which is often a total you have not hit in
          any single meet. Growth on top of that is then damped, because
          projecting a straight line ran 5 percent high at 12 months and 12
          percent high at 36 when it was measured against real held-out
          meets. Projected gain now approaches a ceiling instead of growing
          forever.
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
