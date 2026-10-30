import { describe, expect, it } from 'vitest'
import { candidateFormSchema, type CandidateFormValues } from './schema'
import { validFormValues } from './testing'

const issuesFor = (overrides: Partial<CandidateFormValues>) => {
  const result = candidateFormSchema.safeParse(validFormValues(overrides))
  return result.success ? [] : result.error.issues.map((i) => ({ path: i.path.join('.'), message: i.message }))
}

const pathsFor = (overrides: Partial<CandidateFormValues>) => issuesFor(overrides).map((i) => i.path)

describe('candidateFormSchema', () => {
  it('produces the API payload with normalized values', () => {
    const payload = candidateFormSchema.parse(validFormValues({ skills: ['Python', ' python ', 'FastAPI'] }))

    expect(payload).toMatchObject({
      email: 'asha.verma@example.com',
      phone: '+919876543210',
      linkedin_url: 'https://linkedin.com/in/asha-verma',
      github_url: null,
      portfolio_url: null,
      years_experience: 6.5,
      skills: ['python', 'fastapi'],
      open_to_relocation: true,
      notice_period_days: 30,
      // Indian-style grouping is accepted; the API gets a plain number.
      expected_salary: 1_800_000,
      salary_currency: 'INR',
    })
    expect(payload.experiences[0]).toMatchObject({ end_month: null, description: null })
  })

  it('leaves salary out when it is not given, and rejects amounts the API rejects', () => {
    const payload = candidateFormSchema.parse(validFormValues({ expected_salary: '', salary_currency: '' }))
    expect([payload.expected_salary, payload.salary_currency]).toEqual([null, null])
    expect(pathsFor({ expected_salary: '0' })).toContain('expected_salary')
    expect(pathsFor({ expected_salary: '12.5' })).toContain('expected_salary')
    expect(pathsFor({ expected_salary: '1000000001' })).toContain('expected_salary')
    expect(pathsFor({ salary_currency: 'XYZ' })).toContain('salary_currency')
  })

  it('requires at least one skill', () => {
    expect(pathsFor({ skills: [] })).toContain('skills')
  })

  it.each(['12345', '+0123456789', 'phone'])('rejects phone %s', (phone) => {
    expect(pathsFor({ phone })).toContain('phone')
  })

  it.each(['https://example.com/in/asha', 'https://linkedin.com/company/acme', 'https://linkedin.com/in/'])(
    'rejects LinkedIn URL %s',
    (linkedin_url) => {
      expect(pathsFor({ linkedin_url })).toContain('linkedin_url')
    },
  )

  it('requires https for the portfolio', () => {
    expect(pathsFor({ portfolio_url: 'http://asha.dev' })).toContain('portfolio_url')
  })

  it.each(['-1', '51', '5.25', 'abc', ''])('rejects years of experience %s', (years_experience) => {
    expect(pathsFor({ years_experience })).toContain('years_experience')
  })

  it('requires an end month for past roles', () => {
    const experiences = [{ company: 'A', title: 'T', start_month: '2020-01', is_current: false, end_month: '', description: '' }]
    expect(pathsFor({ experiences })).toContain('experiences.0.end_month')
  })

  it('rejects an end month before the start month', () => {
    const experiences = [
      { company: 'A', title: 'T', start_month: '2020-05', is_current: false, end_month: '2020-01', description: '' },
    ]
    expect(issuesFor({ experiences })).toContainEqual({
      path: 'experiences.0.end_month',
      message: 'End month cannot be before the start month.',
    })
  })

  it('rejects a start month in the future', () => {
    const experiences = [{ company: 'A', title: 'T', start_month: '2999-01', is_current: true, end_month: '', description: '' }]
    expect(pathsFor({ experiences })).toContain('experiences.0.start_month')
  })

  it('allows only one current role', () => {
    const role = { company: 'A', title: 'T', start_month: '2020-01', is_current: true, end_month: '', description: '' }
    expect(pathsFor({ experiences: [role, { ...role, company: 'B' }] })).toContain('experiences')
  })

  it('rejects an education end year before the start year', () => {
    const educations = [{ institution: 'X', degree: '', field_of_study: '', start_year: '2018', end_year: '2015' }]
    expect(pathsFor({ educations })).toContain('educations.0.end_year')
  })

  it('requires a work mode and consent', () => {
    expect(pathsFor({ work_modes: [] })).toContain('work_modes')
    expect(issuesFor({ consent: false })).toContainEqual({
      path: 'consent',
      message: 'You must agree to the privacy notice to continue.',
    })
  })

  it('rejects an unknown country', () => {
    expect(pathsFor({ country_code: 'XX' })).toContain('country_code')
  })

  it('accepts internationalized email addresses like the backend', () => {
    expect(pathsFor({ email: 'josé@example.com' })).not.toContain('email')
  })

  it.each([
    ['portfolio_url', 'https://evil.example\\@asha.dev'],
    ['linkedin_url', 'https://user@linkedin.com/in/x'],
    ['github_url', 'https://github.com/ash a'],
  ] as const)('rejects ambiguous %s %s', (field, url) => {
    expect(pathsFor({ [field]: url })).toContain(field)
  })

  it('rejects experience starting before 1950', () => {
    const experiences = [{ company: 'A', title: 'T', start_month: '0001-01', is_current: false, end_month: '2020-01', description: '' }]
    expect(pathsFor({ experiences })).toContain('experiences.0.start_month')
  })
})
