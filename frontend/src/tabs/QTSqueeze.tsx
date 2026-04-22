// QT Squeeze tab.
//
// Unified filter-panel-driven view of Canadian qualifying-total coverage.
// Replaced the old four-block layout (F/M x Regionals/Nationals showing
// pre-2025 / 2025 / 2027 hypothetical percentages) on 2026-04-22 in
// favour of a single coverage table driven by live-scraped CPU +
// provincial QT data. See data/scrapers/ and the weekly qt_refresh
// GitHub Actions workflow for the pipeline.

import QtLiveCoveragePanel from './QtLiveCoveragePanel'

export default function QTSqueeze({ isActive: _isActive }: { isActive: boolean }) {
  // isActive is accepted for parity with other tabs that gate Recharts
  // rendering on it. This tab has no Recharts components so the flag is
  // unused here -- underscore prefix to silence the lint rule.
  return (
    <div>
      <div className="mb-6">
        <h2 className="text-zinc-100 text-lg font-semibold">QT Squeeze</h2>
        <p className="text-zinc-300 text-sm mt-1 max-w-3xl">
          Percent of Canadian IPF lifters in each weight class whose best SBD
          total in the 24-month qualifying window meets the CPU qualifying
          total. Pick sex, level, age division, effective year, and (for
          2027 Regionals) region or (for Provincials) province to change
          the view.
        </p>
        <details className="mt-2 max-w-3xl">
          <summary className="text-zinc-500 text-xs cursor-pointer hover:text-zinc-300">
            Methodology and caveats
          </summary>
          <div className="text-zinc-500 text-xs mt-2 space-y-1.5">
            <p>
              <span className="text-zinc-400 font-medium">Data source:</span>{' '}
              CPU Nationals and Regionals standards are scraped weekly from
              <em> powerlifting.ca/qualifying-standards </em>and
              <em> /2027qualifications</em>. Ontario Provincial standards are
              scraped from the OPA Dropbox Excel linked from
              <em> ontariopowerlifting.org/qualifying-standards</em>. Other
              provinces currently reuse the CPU Regional standards for their
              provincial meets; the ones that publish separate numbers will
              get their own scrapers in follow-up sessions.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">24-month window:</span>{' '}
              The cohort is lifters whose best SBD total falls in the 24
              months ending March 1 of the effective year. For 2026 that
              means 2024-03-01 through 2026-03-01; for 2027 that means
              2025-03-01 through 2027-03-01.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">Division filter:</span>{' '}
              Uses OpenIPF's Division column, which is federation free-text
              but reliably populated for CPU rows as Open / Sub-Junior /
              Junior / Master 1-4. Choosing a specific division filters both
              the QT threshold and the cohort denominator to that division.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">Scope:</span>{' '}
              Classic (unequipped) + full power (SBD) only. Equipped lifts
              and bench-only events are out of scope; they are parsed from
              the source documents but filtered out before publication.
            </p>
            <p>
              <span className="text-zinc-400 font-medium">Canada + IPF only:</span>{' '}
              The lifter cohort is locked to IPF-sanctioned meets only.
              Non-IPF federations (CPF, WPC, GPC) are excluded at the
              parquet preprocessing step. This site is not affiliated with
              the CPU or IPF.
            </p>
            <p>
              <a
                href="?tab=about"
                className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                See the About tab for full methodology, references, and disclaimers.
              </a>
            </p>
          </div>
        </details>
      </div>

      <QtLiveCoveragePanel />
    </div>
  )
}
