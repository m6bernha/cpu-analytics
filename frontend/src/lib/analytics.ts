// Product analytics: a typed wrapper over Vercel Web Analytics custom events.
//
// Why a wrapper instead of calling `track()` at each site: these event names
// are the schema every future product decision gets read off, so they live in
// one file where a typo is a compile error rather than a row that silently
// never appears in the dashboard. ADR 0002 gates accounts/follows on the
// stateless layer "proving demand", and these events are what proving it
// means.
//
// TWO RULES, both load-bearing:
//
// 1. No user-typed or user-identifying strings as property values. Lifter
//    names, search queries, and roster contents never leave the browser
//    through here. Properties describe WHAT was done, never WHO it was about.
//    Athlete profile popularity is already answerable from pageviews of the
//    real `/athlete/{name}` paths, so nothing is lost by the rule.
// 2. Bucket unbounded numbers before sending. Vercel indexes per distinct
//    property value, so a raw roster size of 1..200 spends 200 slots to
//    answer a question ("do people scout big meets or small ones?") that five
//    buckets answer just as well.

import { track } from '@vercel/analytics'

/** Sizes are reported as ranges, never raw counts. See rule 2 above. */
export function sizeBucket(n: number): string {
  if (n <= 0) return '0'
  if (n <= 10) return '1-10'
  if (n <= 25) return '11-25'
  if (n <= 50) return '26-50'
  if (n <= 100) return '51-100'
  return '100+'
}

// The full event vocabulary. Adding a member here is the only way to add an
// event, which keeps the dashboard's schema and this file in sync.
type EventMap = {
  /** Which tabs actually get used. Tabs are query-string state, so automatic
   *  pageviews cannot tell them apart -- without this every tab is just "/". */
  tab_viewed: { tab: string }
  /** Compare is three clicks deep; this says whether anyone gets there. */
  compare_used: { lifter_count: number }
  /** Engine D shipped at 100% convergence. Does anyone switch off the default? */
  projection_viewed: { engine: string }
  /** Hypothetical-trajectory entry: a power feature buried under search. */
  manual_entry_used: { meets_bucket: string }
  /** Scout is the coach-facing bet. Adoption here decides Phases 2-3. */
  scout_report_generated: { roster_bucket: string; matched_bucket: string }
  /** Sharing is the growth loop. `surface` says which view got shared,
   *  `method` separates the native share sheet from a clipboard copy. */
  share_used: { surface: string; method: string }
  /** Exports are the strongest "this was worth keeping" signal we can see. */
  export_used: { kind: string; surface: string }
}

export function trackEvent<K extends keyof EventMap>(
  name: K,
  props: EventMap[K],
): void {
  // `track` is a no-op until Web Analytics is enabled on the Vercel project
  // and is disabled outside production by default, so this is safe to call
  // unconditionally from anywhere including tests.
  track(name, props as Record<string, string | number | boolean | null>)
}
