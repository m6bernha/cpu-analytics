import { useEffect, useRef, useState } from 'react'
import { type LifterSearchResult } from '../../lib/api'
import { ShareButton } from '../../lib/ShareButton'

function SelectorSearch({
  query,
  setQuery,
  searchResults,
  searchIsLoading,
  selected,
  onSelect,
  onReset,
}: {
  query: string
  setQuery: (v: string) => void
  searchResults: LifterSearchResult[]
  searchIsLoading: boolean
  selected: LifterSearchResult | null
  onSelect: (r: LifterSearchResult) => void
  onReset: () => void
}) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Close the dropdown on outside click. Same pattern as MethodPill.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  // Show dropdown only when actively searching: focused + at least 2 chars
  // typed AND the typed text is not literally the selected lifter's name
  // (otherwise picking a lifter immediately re-opens with that lifter as
  // the only result, which feels noisy).
  const trimmed = query.trim()
  const isSearchingNew = trimmed.length >= 2 && trimmed !== selected?.Name
  const showDropdown = open && isSearchingNew

  return (
    <div className="flex items-center gap-2">
      <div ref={containerRef} className="flex-1 relative">
        <input
          id="ap-search"
          type="text"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            // Clearing the field also drops the selection. Otherwise the
            // chart would keep rendering for a lifter the user just deleted.
            if (e.target.value === '' && selected) onReset()
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          placeholder="Type a name"
          aria-label="Search lifter by name"
          className="w-full pl-4 pr-9 py-2 bg-zinc-800 border border-zinc-700 rounded text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
        />
        {(query.length > 0 || selected) && (
          <button
            type="button"
            onClick={() => {
              onReset()
              setOpen(false)
            }}
            aria-label="Clear lifter"
            title="Clear lifter"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-red-400 text-base leading-none px-1 transition-colors focus:outline-none focus:text-red-400"
          >
            ×
          </button>
        )}
        {showDropdown && (
          <div className="absolute top-full left-0 right-0 mt-1 max-h-72 overflow-y-auto bg-zinc-900 border border-zinc-800 rounded shadow-lg z-10">
            {searchIsLoading && (
              <div className="px-3 py-2 text-zinc-500 text-sm">Searching...</div>
            )}
            {!searchIsLoading && searchResults.length === 0 && (
              <div className="px-3 py-2 text-zinc-500 text-sm">No matches.</div>
            )}
            {searchResults.length > 0 && (
              <ul className="divide-y divide-zinc-800">
                {searchResults.map((r) => (
                  <li key={`${r.Name}-${r.LatestMeetDate}`}>
                    <button
                      type="button"
                      onClick={() => {
                        onSelect(r)
                        setOpen(false)
                      }}
                      className={
                        'w-full text-left px-3 py-2 hover:bg-zinc-800 transition-colors ' +
                        (selected?.Name === r.Name ? 'bg-zinc-900' : '')
                      }
                    >
                      <div className="text-zinc-100 text-sm">{r.Name}</div>
                      <div className="text-zinc-500 text-xs mt-0.5">
                        {r.Sex} · {r.LatestWeightClass} kg ·{' '}
                        {r.LatestEquipment} ·{' '}
                        {r.MeetCount} meet{r.MeetCount === 1 ? '' : 's'} · best{' '}
                        {Math.round(r.BestTotalKg)} kg
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
      <ShareButton ariaLabel="Copy shareable link to this projection" />
    </div>
  )
}

export default SelectorSearch
