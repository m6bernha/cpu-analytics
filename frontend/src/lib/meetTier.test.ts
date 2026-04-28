import { describe, it, expect } from 'vitest'
import { resolveMeetTier, resolveHighestTier } from './meetTier'

describe('resolveMeetTier', () => {
  it('elevates non-Canada meet to international', () => {
    const r = resolveMeetTier({ meetName: 'IPF Worlds', meetCountry: 'Sweden' })
    expect(r.tier).toBe('international')
    expect(r.label).toBe('International')
  })

  it('classifies bare "Nationals" as national', () => {
    expect(resolveMeetTier({ meetName: 'Nationals', meetCountry: 'Canada' }).tier).toBe('national')
  })

  it('classifies "Canadian Nationals" as national', () => {
    expect(resolveMeetTier({ meetName: 'Canadian Nationals', meetCountry: 'Canada' }).tier).toBe('national')
  })

  it('classifies "Canadian Championship" as national', () => {
    expect(resolveMeetTier({ meetName: 'Canadian Championship', meetCountry: 'Canada' }).tier).toBe('national')
  })

  it('classifies "Canadian National Championship" as national', () => {
    expect(resolveMeetTier({ meetName: 'Canadian National Championship', meetCountry: 'Canada' }).tier).toBe('national')
  })

  it('classifies "Western Canadian Championship" as regional', () => {
    expect(resolveMeetTier({ meetName: 'Western Canadian Championship', meetCountry: 'Canada' }).tier).toBe('regional')
  })

  it('classifies "Central Canadian Championship" as regional', () => {
    expect(resolveMeetTier({ meetName: 'Central Canadian Championship', meetCountry: 'Canada' }).tier).toBe('regional')
  })

  it('classifies "Western Canadians" as regional', () => {
    expect(resolveMeetTier({ meetName: 'Western Canadians', meetCountry: 'Canada' }).tier).toBe('regional')
  })

  it('classifies "Alberta Provincials" as provincial', () => {
    expect(resolveMeetTier({ meetName: 'Alberta Provincials', meetCountry: 'Canada' }).tier).toBe('provincial')
  })

  it('classifies "BCPA Provincials" as provincial', () => {
    expect(resolveMeetTier({ meetName: 'BCPA Provincials', meetCountry: 'Canada' }).tier).toBe('provincial')
  })

  it('classifies "BC Provincial Championship" as provincial', () => {
    expect(resolveMeetTier({ meetName: 'BC Provincial Championship', meetCountry: 'Canada' }).tier).toBe('provincial')
  })

  it('classifies "Ontario Open and Masters Provincials" as provincial', () => {
    expect(
      resolveMeetTier({ meetName: 'Ontario Open and Masters Provincials', meetCountry: 'Canada' }).tier,
    ).toBe('provincial')
  })

  it('classifies "BCPA Fall Classic" as local', () => {
    expect(resolveMeetTier({ meetName: 'BCPA Fall Classic', meetCountry: 'Canada' }).tier).toBe('local')
  })

  it('classifies "London Open" as local', () => {
    expect(resolveMeetTier({ meetName: 'London Open', meetCountry: 'Canada' }).tier).toBe('local')
  })

  it('classifies "Belle River Open" as local', () => {
    expect(resolveMeetTier({ meetName: 'Belle River Open', meetCountry: 'Canada' }).tier).toBe('local')
  })

  it('falls back to local for unknown meet name', () => {
    expect(resolveMeetTier({ meetName: 'Xyz Unknown Festival', meetCountry: 'Canada' }).tier).toBe('local')
  })

  it('falls back to local for empty meet name', () => {
    expect(resolveMeetTier({ meetName: '', meetCountry: 'Canada' }).tier).toBe('local')
  })

  it('falls back to local for null meet name', () => {
    expect(resolveMeetTier({ meetName: null, meetCountry: 'Canada' }).tier).toBe('local')
  })

  it('matches case-insensitively', () => {
    expect(resolveMeetTier({ meetName: 'NATIONALS', meetCountry: 'Canada' }).tier).toBe('national')
  })

  it('does not elevate when country is null', () => {
    expect(resolveMeetTier({ meetName: 'Nationals', meetCountry: null }).tier).toBe('national')
  })
})

describe('resolveHighestTier', () => {
  it('returns local for empty meet list', () => {
    expect(resolveHighestTier([]).tier).toBe('local')
  })

  it('takes the highest tier across multiple Canada meets', () => {
    const meets = [
      { meetName: 'BCPA Fall Classic', meetCountry: 'Canada' },
      { meetName: 'Alberta Provincials', meetCountry: 'Canada' },
      { meetName: 'Nationals', meetCountry: 'Canada' },
    ]
    expect(resolveHighestTier(meets).tier).toBe('national')
  })

  it('elevates to international when any meet is non-Canada', () => {
    const meets = [
      { meetName: 'Nationals', meetCountry: 'Canada' },
      { meetName: 'IPF Worlds', meetCountry: 'Sweden' },
    ]
    expect(resolveHighestTier(meets).tier).toBe('international')
  })

  it('returns local when all meets are local-tier', () => {
    const meets = [
      { meetName: 'London Open', meetCountry: 'Canada' },
      { meetName: 'Niagara Open', meetCountry: 'Canada' },
    ]
    expect(resolveHighestTier(meets).tier).toBe('local')
  })
})
