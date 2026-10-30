import { describe, expect, it } from 'vitest'
import { candidateProfileSchema } from '@/features/candidate-profile'
import { detailToFormValues } from './mapping'
import { candidateDetail } from './testing'

describe('detailToFormValues', () => {
  it('produces form values that validate back into the same profile', () => {
    const detail = candidateDetail()

    const payload = candidateProfileSchema.parse(detailToFormValues(detail))

    expect(payload).toMatchObject({
      full_name: detail.full_name,
      email: detail.email,
      phone: null,
      linkedin_url: detail.linkedin_url,
      github_url: null,
      years_experience: 6.5,
      skills: detail.skills,
      work_modes: ['remote', 'hybrid'],
      open_to_relocation: false,
      notice_period_days: 30,
      expected_salary: 1_800_000,
      salary_currency: 'INR',
    })
    expect(payload.experiences).toEqual([
      { company: 'Acme', title: 'Engineer', start_month: '2021-03', is_current: true, end_month: null, description: null },
      { company: 'Globex', title: 'Dev', start_month: '2018-06', is_current: false, end_month: '2021-02', description: 'APIs' },
    ])
    expect(payload.educations[0]).toEqual({
      institution: 'IIT Delhi',
      degree: 'B.Tech',
      field_of_study: null,
      start_year: 2014,
      end_year: 2018,
    })
  })

  it('maps unknown relocation to the empty choice', () => {
    expect(detailToFormValues(candidateDetail({ open_to_relocation: null })).open_to_relocation).toBe('')
  })
})
