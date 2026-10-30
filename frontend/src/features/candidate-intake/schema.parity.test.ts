/**
 * Parity checks between the zod schema and backend/app/features/candidates/schemas.py,
 * using the cases probed during Phase 1 QA. `it.fails` marks a known mismatch: it passes
 * while the mismatch exists and starts failing once it is fixed (then flip it to `it`).
 */
import { describe, expect, it } from 'vitest'
import { candidateFormSchema } from './schema'
import { validFormValues } from './testing'

const parse = (overrides: Parameters<typeof validFormValues>[0]) => candidateFormSchema.safeParse(validFormValues(overrides))

const errorPaths = (overrides: Parameters<typeof validFormValues>[0]) => {
  const result = parse(overrides)
  return result.success ? [] : result.error.issues.map((i) => i.path.join('.'))
}

describe('candidateFormSchema parity with the backend', () => {
  it('normalizes skills like the backend (trim, collapse whitespace, lower-case, dedupe)', () => {
    const result = parse({ skills: ['  Machine   Learning ', 'machine learning', 'MACHINE\tLEARNING', 'C++', '', '  '] })
    expect(result.success && result.data.skills).toEqual(['machine learning', 'c++'])
  })

  it('counts the 50-skill limit after de-duplication', () => {
    const skills = [...Array.from({ length: 50 }, (_, i) => `Skill${i}`), ...Array.from({ length: 10 }, (_, i) => `skill${i}`)]
    expect(parse({ skills }).success).toBe(true)
  })

  it('trims and lower-cases the email', () => {
    const result = parse({ email: '  Mixed.Case@Example.COM ' })
    expect(result.success && result.data.email).toBe('mixed.case@example.com')
  })

  it('strips phone separators to E.164', () => {
    const result = parse({ phone: '+1 (415) 555-0100' })
    expect(result.success && result.data.phone).toBe('+14155550100')
  })

  it.each([
    ['linkedin_url', 'https://evil.example\\@linkedin.com/in/x'],
    ['github_url', 'https://evil.example\\@github.com/x'],
    ['linkedin_url', 'https://linkedin.com@evil.example/in/x'],
    ['github_url', 'https://github.com/'],
    ['portfolio_url', 'javascript://example.com/%0aalert(1)'],
  ] as const)('rejects %s %s', (field, url) => {
    expect(errorPaths({ [field]: url })).toContain(field)
  })

  it('accepts internationalized email local parts like the backend', () => {
    const result = parse({ email: 'JOSÉ@Example.com' })
    expect(result.success && result.data.email).toBe('josé@example.com')
  })

  it('rejects experience start months before 1950 like the backend', () => {
    const experience = { company: 'A', title: 'T', start_month: '1949-12', is_current: true, end_month: '', description: '' }
    expect(errorPaths({ experiences: [experience] })).toContain('experiences.0.start_month')
  })

  // Known mismatch: the backend rejects any "@" in the authority, but WHATWG URL reports an
  // empty username for "https://@host", so the frontend lets it through to a server 422.
  it('rejects an empty userinfo "@" like the backend', () => {
    expect(errorPaths({ linkedin_url: 'https://@linkedin.com/in/x' })).toContain('linkedin_url')
  })

  it('accepts unicode names', () => {
    expect(parse({ full_name: 'José Ñúñez 李小龍', city: 'São Paulo' }).success).toBe(true)
  })

  it('rejects summaries over 3000 characters and accepts exactly 3000', () => {
    expect(errorPaths({ summary: 'x'.repeat(3001) })).toContain('summary')
    expect(parse({ summary: 'x'.repeat(3000) }).success).toBe(true)
  })

  it('rejects years of experience with two decimals or above 50', () => {
    expect(errorPaths({ years_experience: '5.25' })).toContain('years_experience')
    expect(errorPaths({ years_experience: '50.5' })).toContain('years_experience')
    expect(parse({ years_experience: '50' }).success).toBe(true)
  })

  it('limits desired roles to 10', () => {
    expect(errorPaths({ desired_roles: Array.from({ length: 11 }, (_, i) => `role ${i}`) })).toContain('desired_roles')
  })

  // Python counts code points; the limit must not count UTF-16 units (an emoji is two).
  it('counts name length in code points like the backend', () => {
    expect(parse({ full_name: '😀'.repeat(61) }).success).toBe(true)
    expect(errorPaths({ full_name: '😀'.repeat(121) })).toContain('full_name')
  })
})
