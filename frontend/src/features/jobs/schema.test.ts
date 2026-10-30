import { describe, expect, it } from 'vitest'
import { jobSchema } from './schema'
import { validJobValues } from './testing'

const parse = (overrides: Parameters<typeof validJobValues>[0] = {}) => jobSchema.safeParse(validJobValues(overrides))

/** Paths of every issue, or [] when the values are valid. */
const errorPaths = (overrides: Parameters<typeof validJobValues>[0] = {}) => {
  const result = parse(overrides)
  return result.success ? [] : result.error.issues.map((issue) => issue.path.join('.'))
}

describe('jobSchema', () => {
  it('accepts a valid job and normalises it', () => {
    const result = parse({
      title: '  Engineer  ',
      department: '   ',
      country_code: 'DE',
      must_have_skills: ['  Python ', 'python', 'Post  GRES'],
      nice_to_have_skills: [],
      min_years: '3',
      max_years: '',
    })

    expect(result.success && result.data).toMatchObject({
      title: 'Engineer',
      department: null,
      must_have_skills: ['python', 'post gres'],
      nice_to_have_skills: [],
      min_years: 3,
      max_years: null,
    })
  })

  it.each([
    [120, true],
    [121, false],
  ])('title of %i characters is valid: %s', (length, ok) => {
    expect(errorPaths({ title: 't'.repeat(length) }).includes('title')).toBe(!ok)
  })

  it('rejects a blank title', () => {
    expect(errorPaths({ title: '   ' })).toContain('title')
  })

  it.each([
    ['x'.repeat(99), false],
    ['x'.repeat(100), true],
    ['x'.repeat(10_000), true],
    ['x'.repeat(10_001), false],
    [`  ${'x'.repeat(99)}  `, false],
  ])('description length is counted after trimming (%#)', (description, ok) => {
    expect(errorPaths({ description }).includes('description')).toBe(!ok)
  })

  it.each([
    ['-0.1', false],
    ['0', true],
    ['50', true],
    ['50.1', false],
    ['3.25', false],
    ['4.5', true],
    ['abc', false],
    ['', false],
  ])('minimum years %s is valid: %s', (min_years, ok) => {
    expect(errorPaths({ min_years, max_years: '' }).includes('min_years')).toBe(!ok)
  })

  it('requires the maximum to be at least the minimum', () => {
    expect(errorPaths({ min_years: '5', max_years: '4' })).toEqual(['max_years'])
    expect(parse({ min_years: '5', max_years: '5' }).success).toBe(true)
  })

  it.each([
    [[], false],
    [['a', 'A', ' a '], true],
    [Array.from({ length: 20 }, (_, i) => `skill ${i}`), true],
    [Array.from({ length: 21 }, (_, i) => `skill ${i}`), false],
    [['s'.repeat(50)], true],
    [['s'.repeat(51)], false],
  ])('must-have skills %# are valid after normalising: %s', (must_have_skills, ok) => {
    // A too-long tag reports on the item (must_have_skills.0), the count on the list.
    const paths = errorPaths({ must_have_skills, nice_to_have_skills: [] })
    expect(paths.some((path) => path.startsWith('must_have_skills'))).toBe(!ok)
  })

  it('caps nice-to-have skills at 20', () => {
    const skills = Array.from({ length: 21 }, (_, i) => `extra ${i}`)
    expect(errorPaths({ nice_to_have_skills: skills })).toContain('nice_to_have_skills')
  })

  it('rejects a skill that is both must-have and nice-to-have', () => {
    expect(errorPaths({ must_have_skills: ['Python'], nice_to_have_skills: ['python'] })).toEqual(['nice_to_have_skills'])
  })

  it('needs no location for a remote job', () => {
    const result = parse({ work_mode: 'remote', city: '', country_code: '' })
    expect(result.success && result.data).toMatchObject({ city: null, country_code: null })
  })

  it.each(['hybrid', 'onsite'] as const)('requires a city and country for a %s job', (work_mode) => {
    expect(errorPaths({ work_mode, city: '', country_code: '' }).sort()).toEqual(['city', 'country_code'])
  })

  it('requires a country whenever a city is given, even for a remote job', () => {
    expect(errorPaths({ work_mode: 'remote', city: 'Paris', country_code: '' })).toEqual(['country_code'])
  })

  it('rejects an unknown country code', () => {
    expect(errorPaths({ country_code: 'XX' })).toContain('country_code')
  })

  it('rejects unknown enum values', () => {
    expect(errorPaths({ work_mode: 'moon' as never })).toContain('work_mode')
    expect(errorPaths({ employment_type: 'gig' as never })).toContain('employment_type')
    expect(errorPaths({ status: 'archived' as never })).toContain('status')
  })
})
