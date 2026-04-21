// Athlete Projection (BETA) tab.
//
// This is the coach-view feature: given a lifter and a target date, predict
// where they'll be on that date and how far from the QT they'll sit. Still
// under heavy design -- see NEXT_STEPS.md and the open roundtable question
// about how to weight a lifter's own trajectory vs the cohort average.

export default function AthleteProjection({ isActive: _isActive }: { isActive: boolean }) {
  return (
    <div>
      <div className="mb-6">
        <h2 className="text-zinc-100 text-lg font-semibold flex items-baseline gap-2">
          Athlete Projection
          <span className="text-amber-500 text-xs uppercase tracking-wide">
            Beta
          </span>
        </h2>
        <p className="text-zinc-400 text-sm mt-1 max-w-3xl">
          Predict where a lifter will be on a target date, and how far from
          Regionals or Nationals qualifying totals they'll sit at that point.
          Combines the lifter's own trajectory (from their meet history) with
          the cohort-average progression rate for their sex, class, equipment,
          and age category.
        </p>
      </div>

      <div className="p-4 border border-amber-900/40 bg-amber-950/20 rounded max-w-3xl mb-6">
        <div className="text-amber-300 text-sm font-semibold mb-1">
          Under construction
        </div>
        <div className="text-amber-400/80 text-xs">
          The math here is non-trivial and needs to be worked through
          explicitly before we ship any numbers. The open question: how much
          weight should be placed on a lifter's own trajectory (which may be
          noisy, non-monotonic, or based on few meets) vs the cohort-average
          trend (stable, but assumes the lifter tracks the average)?
        </div>
      </div>

      <div className="text-zinc-500 text-sm max-w-3xl">
        <p className="mb-2">Once launched, this tab will let you:</p>
        <ul className="list-disc list-inside space-y-1 text-zinc-400">
          <li>Pick any lifter in the dataset, or enter your own meets manually.</li>
          <li>Pick a target date (for example, March 1, 2027, for Nationals).</li>
          <li>See the predicted total on that date with a confidence band.</li>
          <li>See the kg gap to Regionals and Nationals QTs for the target era.</li>
          <li>Adjust the weight placed on personal trajectory vs cohort average.</li>
        </ul>
      </div>
    </div>
  )
}
