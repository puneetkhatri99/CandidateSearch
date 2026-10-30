import { type ProfileFormValues, WORK_MODES } from '@/features/candidate-profile'
import type { CandidateDetail } from './types'

type WorkMode = (typeof WORK_MODES)[number]
const isWorkMode = (value: string): value is WorkMode => (WORK_MODES as readonly string[]).includes(value)

const text = (value: string | null) => value ?? ''
const numberText = (value: number | null) => (value === null ? '' : String(value))

/** Turns a stored profile into the string-based values the edit form works with. */
export function detailToFormValues(detail: CandidateDetail): ProfileFormValues {
  return {
    full_name: detail.full_name,
    email: detail.email,
    phone: text(detail.phone),
    city: detail.city,
    country_code: detail.country_code,
    linkedin_url: text(detail.linkedin_url),
    github_url: text(detail.github_url),
    portfolio_url: text(detail.portfolio_url),
    headline: detail.headline,
    years_experience: String(detail.years_experience),
    skills: detail.skills,
    summary: detail.summary,
    experiences: detail.experiences.map((e) => ({
      company: e.company,
      title: e.title,
      start_month: e.start_month,
      is_current: e.is_current,
      end_month: text(e.end_month),
      description: text(e.description),
    })),
    educations: detail.educations.map((e) => ({
      institution: e.institution,
      degree: text(e.degree),
      field_of_study: text(e.field_of_study),
      start_year: numberText(e.start_year),
      end_year: numberText(e.end_year),
    })),
    desired_roles: detail.desired_roles,
    work_modes: detail.work_modes.filter(isWorkMode),
    open_to_relocation: detail.open_to_relocation === null ? '' : detail.open_to_relocation ? 'yes' : 'no',
    notice_period_days: numberText(detail.notice_period_days),
    expected_salary: numberText(detail.expected_salary),
    salary_currency: text(detail.salary_currency),
  }
}
