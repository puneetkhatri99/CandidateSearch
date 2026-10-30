/**
 * Parity checks between the zod schema and backend/app/features/jobs/schemas.py. Each case
 * mirrors a case in backend/app/features/jobs/tests/test_schemas.py: change them together.
 */
import { describe, expect, it } from 'vitest'
import { jobSchema } from './schema'
import { validJobValues } from './testing'

const parse = (overrides: Parameters<typeof validJobValues>[0] = {}) => jobSchema.safeParse(validJobValues(overrides))

const messageAt = (path: string, overrides: Parameters<typeof validJobValues>[0]) => {
  const result = parse(overrides)
  return result.success ? undefined : result.error.issues.find((issue) => issue.path.join('.') === path)?.message
}

describe('jobSchema parity with the backend', () => {
  it('normalises skills like the backend (trim, collapse whitespace, lower-case, dedupe)', () => {
    const result = parse({ must_have_skills: ['  Machine   Learning ', 'machine learning', 'MACHINE\tLEARNING', 'C++', '', '  '] })
    expect(result.success && result.data.must_have_skills).toEqual(['machine learning', 'c++'])
  })

  it('counts skill limits after de-duplication', () => {
    const skills = [...Array.from({ length: 20 }, (_, i) => `Skill${i}`), ...Array.from({ length: 10 }, (_, i) => `skill${i}`)]
    expect(parse({ must_have_skills: skills, nice_to_have_skills: [] }).success).toBe(true)
  })

  it('uses the backend wording for the rules that depend on two fields', () => {
    expect(messageAt('max_years', { min_years: '5', max_years: '4' })).toBe('Maximum years cannot be less than the minimum.')
    expect(messageAt('nice_to_have_skills', { must_have_skills: ['go'], nice_to_have_skills: ['Go'] })).toBe(
      "A skill can't be both must-have and nice-to-have.",
    )
    expect(messageAt('city', { work_mode: 'onsite', city: '', country_code: 'DE' })).toBe('Enter the city for a hybrid or onsite role.')
    expect(messageAt('country_code', { work_mode: 'remote', city: 'Paris', country_code: '' })).toBe('Select the country.')
  })

  it('uses the backend rules and wording for the pay range', () => {
    expect(messageAt('salary_currency', { salary_min: '100' })).toBe('Select the currency.')
    expect(messageAt('salary_currency', { salary_currency: 'INR' })).toBe('Enter the salary, or clear the currency.')
    expect(messageAt('salary_max', { salary_min: '10', salary_max: '5', salary_currency: 'INR' })).toBe(
      'Maximum pay cannot be less than the minimum.',
    )
    expect(messageAt('salary_min', { salary_min: '0', salary_currency: 'INR' })).toBeDefined()
    const result = parse({ salary_min: '15,00,000', salary_max: '', salary_currency: 'INR' })
    expect(result.success && [result.data.salary_min, result.data.salary_max]).toEqual([1_500_000, null])
  })

  it('rejects the years the backend rejects', () => {
    expect(messageAt('min_years', { min_years: '3.25' })).toBeDefined()
    expect(messageAt('min_years', { min_years: '50.1' })).toBeDefined()
    expect(messageAt('min_years', { min_years: '-0.1' })).toBeDefined()
    expect(parse({ min_years: '50', max_years: '' }).success).toBe(true)
  })

  it('counts the description in code points like the backend', () => {
    expect(parse({ description: '😀'.repeat(100) }).success).toBe(true)
    expect(parse({ description: '😀'.repeat(99) }).success).toBe(false)
  })

  it('sends nothing the backend would refuse as an unknown field', () => {
    const result = parse()
    expect(result.success && Object.keys(result.data).sort()).toEqual(
      [
        'city',
        'country_code',
        'department',
        'description',
        'employment_type',
        'max_years',
        'min_years',
        'must_have_skills',
        'nice_to_have_skills',
        'salary_currency',
        'salary_max',
        'salary_min',
        'status',
        'title',
        'work_mode',
      ].sort(),
    )
  })
})
