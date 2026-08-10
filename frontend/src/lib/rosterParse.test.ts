// Roster parsing against the shapes entry lists actually arrive in.
//
// The Scout MVP shipped with a parser that understood one thing: a bare
// name per line. Real entry lists are spreadsheet exports with weight
// class and division columns, "Last, First" lists, numbered lists, or
// text dragged out of a PDF. That gap is why the Sunny Daze 2026 roster
// was reconstructed by hand.
//
// Most of what follows are negative controls. A format-guessing parser
// fails SILENTLY: it returns names, they just are not the right names,
// and the first sign of trouble is a scouting report where half the field
// is unranked. So each heuristic is paired with a case that must NOT
// trigger it.

import { describe, expect, it } from 'vitest'

import { parseRoster, parseRosterDetailed } from './scoutOverrides'
import sunnyDaze from './__fixtures__/sunnyDaze2026Roster.json'

const names = (text: string) => parseRoster(text).map((e) => e.name)

describe('bare lines (the format that already worked)', () => {
  it('reads one name per line and tags homies', () => {
    const entries = parseRoster('Jane Doe\n@John Smith\nAmelie Picher-Plante')
    expect(entries).toEqual([
      { name: 'Jane Doe', is_homie: false },
      { name: 'John Smith', is_homie: true },
      { name: 'Amelie Picher-Plante', is_homie: false },
    ])
    expect(parseRosterDetailed('Jane Doe\nJohn Smith').format).toBe('lines')
  })

  it('collapses internal whitespace, because the backend matches exactly', () => {
    expect(names('Jane   Doe')).toEqual(['Jane Doe'])
  })

  it('strips list markers and bullets', () => {
    expect(names('1. Jane Doe\n2) John Smith\n- Amy Roe\n• Bo Lin')).toEqual([
      'Jane Doe', 'John Smith', 'Amy Roe', 'Bo Lin',
    ])
  })

  it('unions homie tags across duplicates instead of dropping the tag', () => {
    const entries = parseRoster('Jane Doe\n@jane doe')
    expect(entries).toEqual([{ name: 'Jane Doe', is_homie: true }])
    expect(parseRosterDetailed('Jane Doe\n@jane doe').duplicates).toBe(1)
  })
})

describe('trailing weight class', () => {
  it('strips a trailing class from a bare line', () => {
    expect(names('Jane Doe 83\nJohn Smith 120+\nAmy Roe 74kg')).toEqual([
      'Jane Doe', 'John Smith', 'Amy Roe',
    ])
  })

  it('NEGATIVE CONTROL: leaves an OpenIPF duplicate-name suffix alone', () => {
    // "Anthony Wong #2" is a real OpenIPF name and the `#2` is part of the
    // string the backend matches on. Stripping it would unrank the lifter,
    // and the sitemap tests already lock this name shape elsewhere.
    expect(names('Anthony Wong #2')).toEqual(['Anthony Wong #2'])
    expect(names('Blake Barrett #1')).toEqual(['Blake Barrett #1'])
  })

  it('NEGATIVE CONTROL: does not eat a name that is only a number', () => {
    // Nonsense input, but it must not silently vanish.
    expect(names('83')).toEqual(['83'])
  })
})

describe('tab-separated spreadsheet paste', () => {
  const sheet = [
    'Name\tWeight Class\tDivision\tTeam',
    'Jane Doe\t72\tOpen\tVireo Powerlifting',
    'John Smith\t83\tJuniors\tIron House',
    'Amy Roe\t63\tOpen\tVireo Powerlifting',
  ].join('\n')

  it('picks the name column and drops the header', () => {
    const result = parseRosterDetailed(sheet)
    expect(result.format).toBe('tab')
    expect(result.droppedHeader).toBe(true)
    expect(result.discardedColumns).toBe(3)
    expect(result.entries.map((e) => e.name)).toEqual([
      'Jane Doe', 'John Smith', 'Amy Roe',
    ])
  })

  it('finds the name column even when it is not first', () => {
    const shifted = [
      'Lot\tDivision\tLifter',
      '1\tOpen\tJane Doe',
      '2\tJuniors\tJohn Smith',
    ].join('\n')
    expect(names(shifted)).toEqual(['Jane Doe', 'John Smith'])
  })

  it('keeps @ homie tagging in column mode', () => {
    const tagged = 'Jane Doe\t72\nAmy Roe\t63'.replace('Jane', '@Jane')
    const entries = parseRoster(tagged)
    expect(entries[0]).toEqual({ name: 'Jane Doe', is_homie: true })
    expect(entries[1].is_homie).toBe(false)
  })
})

describe('comma-separated input', () => {
  it('reads "Last, First" and reorders it', () => {
    const result = parseRosterDetailed('Doe, Jane\nSmith, John\nRoe, Amy')
    expect(result.format).toBe('last-first')
    expect(result.entries.map((e) => e.name)).toEqual([
      'Jane Doe', 'John Smith', 'Amy Roe',
    ])
  })

  it('drops a "Last, First" header row', () => {
    const result = parseRosterDetailed('Last,First\nDoe, Jane\nSmith, John')
    expect(result.droppedHeader).toBe(true)
    expect(result.entries.map((e) => e.name)).toEqual(['Jane Doe', 'John Smith'])
  })

  it('NEGATIVE CONTROL: name plus division is not "Last, First"', () => {
    // The silent failure this guards: "Open Jane Doe".
    const result = parseRosterDetailed('Jane Doe, Open\nJohn Smith, Juniors')
    expect(result.format).toBe('comma')
    expect(result.entries.map((e) => e.name)).toEqual(['Jane Doe', 'John Smith'])
  })

  it('NEGATIVE CONTROL: name plus team is not "Last, First"', () => {
    // The silent failure this guards: "Vireo Powerlifting Jane Doe".
    const result = parseRosterDetailed(
      'Jane Doe, Vireo Powerlifting\nJohn Smith, Iron House',
    )
    expect(result.format).toBe('comma')
    expect(result.entries.map((e) => e.name)).toEqual(['Jane Doe', 'John Smith'])
  })

  it('NEGATIVE CONTROL: a lone comma in one name does not flip the whole list', () => {
    // Below the 60% majority, so this stays a plain line list.
    const text = 'Jane Doe\nJohn Smith\nAmy Roe\nBo Lin\nSmith, Cal'
    expect(parseRosterDetailed(text).format).toBe('lines')
  })

  it('handles a full CSV with a weight class column', () => {
    const csv = [
      'Name,Weight Class,Division',
      'Jane Doe,72,Open',
      'John Smith,83,Open',
    ].join('\n')
    const result = parseRosterDetailed(csv)
    expect(result.droppedHeader).toBe(true)
    expect(result.entries.map((e) => e.name)).toEqual(['Jane Doe', 'John Smith'])
  })
})

describe('header handling', () => {
  it('NEGATIVE CONTROL: a surname that is also a header word survives', () => {
    // "Place" is a real surname and a column header. Dropping the row
    // requires EVERY field to be a header word, so this must not drop.
    const result = parseRosterDetailed('Place, Sarah\nDoe, Jane')
    expect(result.droppedHeader).toBe(false)
    expect(result.entries.map((e) => e.name)).toEqual(['Sarah Place', 'Jane Doe'])
  })

  it('NEGATIVE CONTROL: a single-line roster is never treated as a header', () => {
    expect(names('Name')).toEqual(['Name'])
  })
})

describe('accents and punctuation survive', () => {
  it('keeps accented and hyphenated names byte for byte', () => {
    // These are real OpenIPF names from the Canadian pool, and the backend
    // matches on the exact string.
    expect(names('Amélie Picher-Plante\nFrédérick Gamache\nCatherine Gagné')).toEqual([
      'Amélie Picher-Plante', 'Frédérick Gamache', 'Catherine Gagné',
    ])
  })

  it('keeps apostrophes', () => {
    expect(names("Sean O'Brien")).toEqual(["Sean O'Brien"])
  })
})

describe('empty and degenerate input', () => {
  it('returns nothing for blank input', () => {
    expect(parseRoster('')).toEqual([])
    expect(parseRoster('   \n\n  ')).toEqual([])
  })

  it('ignores a bare @ with no name', () => {
    expect(parseRoster('@\nJane Doe')).toEqual([
      { name: 'Jane Doe', is_homie: false },
    ])
  })
})

describe('regression: the real Sunny Daze 2026 roster', () => {
  // The 80-name roster the Scout MVP was smoke-tested against on
  // 2026-05-25, matching the reference PDF exactly (42 matched, 38
  // unranked, 7 classes, 4 homies). The parser rewrite must not disturb
  // the one case it is known to get right.
  it('round-trips all 80 names and all 4 homie tags', () => {
    const result = parseRosterDetailed(sunnyDaze.pasted)
    expect(result.format).toBe('lines')
    expect(result.droppedHeader).toBe(false)
    expect(result.duplicates).toBe(0)
    expect(result.entries.map((e) => e.name)).toEqual(sunnyDaze.names)
    expect(
      result.entries.filter((e) => e.is_homie).map((e) => e.name),
    ).toEqual(sunnyDaze.homies)
  })

  it('survives the same roster pasted as a spreadsheet column', () => {
    // Same names, now with weight class and division columns beside them,
    // which is how the list would actually leave a meet director's sheet.
    const sheet = [
      'Name\tWeight Class\tDivision',
      ...sunnyDaze.names.map((n, i) => `${n}\t${[74, 83, 93, 105, 120][i % 5]}\tOpen`),
    ].join('\n')
    const result = parseRosterDetailed(sheet)
    expect(result.format).toBe('tab')
    expect(result.droppedHeader).toBe(true)
    expect(result.entries.map((e) => e.name)).toEqual(sunnyDaze.names)
  })
})
