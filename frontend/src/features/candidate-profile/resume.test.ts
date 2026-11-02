import { describe, expect, it } from 'vitest'
import { fillFromResume, type ProfileSuggestion } from './resume'
import { emptyProfile } from './schema'

const suggestion = (overrides: Partial<ProfileSuggestion> = {}): ProfileSuggestion => ({
  full_name: 'Priya Raman',
  email: 'priya@example.com',
  phone: '+91 98765 43210',
  city: 'Pune',
  country_code: 'IN',
  linkedin_url: null,
  github_url: 'https://github.com/priya',
  portfolio_url: null,
  headline: 'Backend Engineer',
  years_experience: 6.5,
  skills: ['python'],
  experiences: [],
  educations: [{ institution: 'COEP', degree: null, field_of_study: null, start_year: 2013, end_year: null }],
  ...overrides,
})

describe('fillFromResume', () => {
  it('fills every empty field it has a value for, in form order', () => {
    const { values, filled } = fillFromResume(emptyProfile(), suggestion())

    expect(values).toMatchObject({ full_name: 'Priya Raman', country_code: 'IN', years_experience: '6.5', skills: ['python'] })
    expect(values.educations).toEqual([{ institution: 'COEP', degree: '', field_of_study: '', start_year: '2013', end_year: '' }])
    expect(filled).toEqual([
      'Full name', 'Email', 'Phone', 'City', 'Country', 'GitHub', 'Headline', 'Years of experience', 'Skills', 'Education',
    ])
  })

  it('never overwrites what was typed', () => {
    const current = { ...emptyProfile(), full_name: 'Typed', skills: ['go'], years_experience: '3' }

    const { values, filled } = fillFromResume(current, suggestion())

    expect(values.full_name).toBeUndefined()
    expect(values.skills).toBeUndefined()
    expect(values.years_experience).toBeUndefined()
    expect(filled).not.toContain('Full name')
  })

  it('skips a country the form does not offer', () => {
    expect(fillFromResume(emptyProfile(), suggestion({ country_code: 'XX' })).values.country_code).toBeUndefined()
  })
})
