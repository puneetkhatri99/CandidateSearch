/** Reading a resume into the profile form. Mirrors backend/app/features/resumes/schemas.py. */
import { apiRequest } from '@/shared/api/client'
import { COUNTRIES } from '@/shared/data/countries'
import type { EducationFormValues, ExperienceFormValues, ProfileFormValues } from './schema'

export const MAX_RESUME_BYTES = 10 * 1024 * 1024
export const RESUME_FILE_TYPES = '.pdf,.doc,.docx,.txt'

export interface ProfileSuggestion {
  full_name: string | null
  email: string | null
  phone: string | null
  city: string | null
  country_code: string | null
  linkedin_url: string | null
  github_url: string | null
  portfolio_url: string | null
  headline: string | null
  years_experience: number | null
  skills: string[]
  experiences: {
    company: string
    title: string
    start_month: string | null
    is_current: boolean
    end_month: string | null
    description: string | null
  }[]
  educations: {
    institution: string
    degree: string | null
    field_of_study: string | null
    start_year: number | null
    end_year: number | null
  }[]
}

export interface ResumeRead {
  resume_ref: string
  profile: ProfileSuggestion
}

/** The file goes as the raw body; ResumeAI works out the type from the content. */
export function readResume(file: File) {
  return apiRequest<ResumeRead>('/api/v1/resumes', {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': 'application/octet-stream' },
  })
}

const TEXT_FIELDS = [
  ['full_name', 'Full name'],
  ['email', 'Email'],
  ['phone', 'Phone'],
  ['city', 'City'],
  ['country_code', 'Country'],
  ['linkedin_url', 'LinkedIn'],
  ['github_url', 'GitHub'],
  ['portfolio_url', 'Portfolio'],
  ['headline', 'Headline'],
] as const

const COUNTRY_CODES = new Set(COUNTRIES.map((c) => c.code))

export interface Fill {
  values: Partial<ProfileFormValues>
  /** Labels of the fields filled, in form order, to tell the person what to check. */
  filled: string[]
}

/** The suggested values for fields that are still empty; nothing typed is overwritten. */
export function fillFromResume(current: ProfileFormValues, s: ProfileSuggestion): Fill {
  const values: Partial<ProfileFormValues> = {}
  const filled: string[] = []
  for (const [name, label] of TEXT_FIELDS) {
    const suggested = s[name]
    if (!suggested || current[name].trim() !== '') continue
    if (name === 'country_code' && !COUNTRY_CODES.has(suggested)) continue
    values[name] = suggested
    filled.push(label)
  }
  if (s.years_experience !== null && current.years_experience.trim() === '') {
    values.years_experience = String(s.years_experience)
    filled.push('Years of experience')
  }
  if (s.skills.length > 0 && current.skills.length === 0) {
    values.skills = s.skills
    filled.push('Skills')
  }
  if (s.experiences.length > 0 && current.experiences.length === 0) {
    values.experiences = s.experiences.map(
      (e): ExperienceFormValues => ({
        company: e.company,
        title: e.title,
        start_month: e.start_month ?? '',
        is_current: e.is_current,
        end_month: e.end_month ?? '',
        description: e.description ?? '',
      }),
    )
    filled.push('Experience')
  }
  if (s.educations.length > 0 && current.educations.length === 0) {
    values.educations = s.educations.map(
      (e): EducationFormValues => ({
        institution: e.institution,
        degree: e.degree ?? '',
        field_of_study: e.field_of_study ?? '',
        start_year: e.start_year === null ? '' : String(e.start_year),
        end_year: e.end_year === null ? '' : String(e.end_year),
      }),
    )
    filled.push('Education')
  }
  return { values, filled }
}
