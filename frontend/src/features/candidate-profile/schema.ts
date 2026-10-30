/**
 * Candidate profile validation, shared by the public form and the staff pages. Mirrors
 * CandidateProfile in backend/app/features/candidates/schemas.py;
 * change both together. The backend stays the source of truth.
 */
import { z } from 'zod'
import { COUNTRIES } from '@/shared/data/countries'
import { salaryCurrency, yearlySalary } from '@/shared/forms/salary'
import { normalizeTag, tagList } from '@/shared/forms/tags'

// Re-exported so the profile components keep one import for everything schema-related.
export { normalizeTag }

export const WORK_MODES = ['remote', 'hybrid', 'onsite'] as const
export const WORK_MODE_LABELS: Record<(typeof WORK_MODES)[number], string> = {
  remote: 'Remote',
  hybrid: 'Hybrid',
  onsite: 'On-site',
}
export const MAX_EXPERIENCES = 15
export const MAX_EDUCATIONS = 10
export const MAX_SKILLS = 50
export const MAX_DESIRED_ROLES = 10

const COUNTRY_CODES = new Set(COUNTRIES.map((c) => c.code))
const PHONE_RE = /^\+[1-9]\d{6,14}$/
const YEAR_MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/
const YEARS_RE = /^\d{1,2}(\.\d)?$/
// Backslashes, whitespace and control characters make the host a browser opens differ from
// the host we validate, so they're rejected outright (same rule as the backend).
// oxlint-disable-next-line no-control-regex
const URL_UNSAFE_CHARS_RE = /[\\\s\u0000-\u001f\u007f]/
const MIN_YEAR = 1950
const MIN_MONTH = `${MIN_YEAR}-01`
const MAX_URL_LENGTH = 300

/** "YYYY-MM" for the current UTC month, matching the backend's comparison. */
export const currentMonth = () => new Date().toISOString().slice(0, 7)

const blankToNull = (value: string) => (value === '' ? null : value)

const requiredText = (label: string, min: number, max: number) =>
  z
    .string()
    .trim()
    .min(min, min <= 1 ? `${label} is required.` : `${label} must be at least ${min} characters.`)
    .max(max, `${label} must be at most ${max} characters.`)

const optionalText = (label: string, max: number) =>
  z.string().trim().max(max, `${label} must be at most ${max} characters.`).transform(blankToNull)

const optionalInt = (min: number, max: number, message: string) =>
  z
    .string()
    .trim()
    .refine((v) => v === '' || (/^\d+$/.test(v) && Number(v) >= min && Number(v) <= max), message)
    .transform((v) => (v === '' ? null : Number(v)))

const urlField = (check: (url: URL) => string | null) =>
  z
    .string()
    .trim()
    .transform((value, ctx) => {
      if (value === '') return null
      const withScheme = value.includes('://') ? value : `https://${value}`
      let url: URL
      try {
        url = new URL(withScheme)
      } catch {
        ctx.addIssue({ code: 'custom', message: 'Enter a valid URL.' })
        return z.NEVER
      }
      // Check the raw authority: the URL parser reports "https://@host" as an empty username.
      const authority = withScheme.slice(withScheme.indexOf('://') + 3).split(/[/?#]/, 1)[0] ?? ''
      const ambiguous = URL_UNSAFE_CHARS_RE.test(withScheme) || authority.includes('@')
      const problem =
        !['http:', 'https:'].includes(url.protocol) || !url.hostname.includes('.') || ambiguous
          ? 'Enter a valid URL.'
          : withScheme.length > MAX_URL_LENGTH
            ? `Must be at most ${MAX_URL_LENGTH} characters.`
            : check(url)
      if (problem) {
        ctx.addIssue({ code: 'custom', message: problem })
        return z.NEVER
      }
      return withScheme
    })

const hostIs = (url: URL, domain: string) => url.hostname === domain || url.hostname.endsWith(`.${domain}`)
const pathAfter = (url: URL, prefix: string) =>
  url.pathname.startsWith(prefix) && url.pathname.replace(/\/+$/, '').length > prefix.length

const experienceSchema = z
  .object({
    company: requiredText('Company', 1, 120),
    title: requiredText('Title', 1, 120),
    start_month: z
      .string()
      .regex(YEAR_MONTH_RE, 'Use the format YYYY-MM.')
      .refine((v) => v <= currentMonth(), 'Start month cannot be in the future.')
      .refine((v) => v >= MIN_MONTH, `Start month must be ${MIN_YEAR} or later.`),
    is_current: z.boolean(),
    end_month: z.string(),
    description: optionalText('Description', 2000),
  })
  .superRefine((exp, ctx) => {
    const issue = (message: string) => ctx.addIssue({ code: 'custom', path: ['end_month'], message })
    if (exp.is_current) {
      if (exp.end_month) issue('Leave the end month empty for a current role.')
    } else if (!exp.end_month) {
      issue('End month is required unless this is your current role.')
    } else if (!YEAR_MONTH_RE.test(exp.end_month)) {
      issue('Use the format YYYY-MM.')
    } else if (exp.end_month < exp.start_month) {
      issue('End month cannot be before the start month.')
    } else if (exp.end_month > currentMonth()) {
      issue('End month cannot be in the future.')
    }
  })
  .transform((exp) => ({ ...exp, end_month: exp.is_current ? null : exp.end_month }))

const maxEducationYear = new Date().getUTCFullYear() + 7
const yearMessage = `Enter a year between ${MIN_YEAR} and ${maxEducationYear}.`

const educationSchema = z
  .object({
    institution: requiredText('Institution', 1, 200),
    degree: optionalText('Degree', 120),
    field_of_study: optionalText('Field of study', 120),
    start_year: optionalInt(MIN_YEAR, maxEducationYear, yearMessage),
    end_year: optionalInt(MIN_YEAR, maxEducationYear, yearMessage),
  })
  .superRefine((edu, ctx) => {
    if (edu.start_year !== null && edu.end_year !== null && edu.end_year < edu.start_year) {
      ctx.addIssue({ code: 'custom', path: ['end_year'], message: 'End year cannot be before the start year.' })
    }
  })

export const candidateProfileSchema = z.object({
  full_name: requiredText('Full name', 2, 120),
  email: z
    .string()
    .trim()
    .max(254, 'Email must be at most 254 characters.')
    // Unicode-aware like the backend's email-validator; deliverability rules stay server-side.
    .pipe(z.email({ pattern: z.regexes.unicodeEmail, error: 'Enter a valid email address.' }))
    .transform((v) => v.toLowerCase()),
  phone: z
    .string()
    .trim()
    .transform((value, ctx) => {
      if (value === '') return null
      const phone = value.replace(/[\s().-]/g, '')
      if (!PHONE_RE.test(phone)) {
        ctx.addIssue({ code: 'custom', message: 'Use international format, e.g. +919876543210.' })
        return z.NEVER
      }
      return phone
    }),
  city: requiredText('City', 1, 100),
  country_code: z.string().refine((v) => COUNTRY_CODES.has(v), 'Select a country.'),

  linkedin_url: urlField((url) =>
    !hostIs(url, 'linkedin.com')
      ? 'Must be a linkedin.com URL.'
      : !pathAfter(url, '/in/')
        ? 'Must be a linkedin.com/in/... profile URL.'
        : null,
  ),
  github_url: urlField((url) =>
    !hostIs(url, 'github.com') ? 'Must be a github.com URL.' : !pathAfter(url, '/') ? 'Add your GitHub username.' : null,
  ),
  portfolio_url: urlField((url) => (url.protocol !== 'https:' ? 'Enter a valid https:// URL.' : null)),

  headline: requiredText('Headline', 2, 120),
  years_experience: z
    .string()
    .trim()
    .refine((v) => YEARS_RE.test(v) && Number(v) <= 50, 'Enter a number from 0 to 50 (at most one decimal).')
    .transform(Number),
  skills: tagList('skill', 1, MAX_SKILLS, 50),
  summary: requiredText('Summary', 50, 3000),

  experiences: z
    .array(experienceSchema)
    .max(MAX_EXPERIENCES, `Add at most ${MAX_EXPERIENCES} roles.`)
    .refine((list) => list.filter((e) => e.is_current).length <= 1, 'Only one role can be marked as current.'),
  educations: z.array(educationSchema).max(MAX_EDUCATIONS, `Add at most ${MAX_EDUCATIONS} entries.`),

  desired_roles: tagList('role', 0, MAX_DESIRED_ROLES, 120),
  work_modes: z.array(z.enum(WORK_MODES)).min(1, 'Select at least one work mode.'),
  open_to_relocation: z.enum(['', 'yes', 'no']).transform((v) => (v === '' ? null : v === 'yes')),
  notice_period_days: optionalInt(0, 180, 'Enter a number of days from 0 to 180.'),
  // Amount and currency must come together; that two-field rule is checked by the API only,
  // because other forms .extend() this schema and zod can't extend a refined object.
  expected_salary: yearlySalary,
  salary_currency: salaryCurrency,
})

export type ProfileFormValues = z.input<typeof candidateProfileSchema>
export type ProfilePayload = z.output<typeof candidateProfileSchema>
export type ExperienceFormValues = ProfileFormValues['experiences'][number]
export type EducationFormValues = ProfileFormValues['educations'][number]

export const emptyExperience = (): ExperienceFormValues => ({
  company: '',
  title: '',
  start_month: '',
  is_current: false,
  end_month: '',
  description: '',
})

export const emptyEducation = (): EducationFormValues => ({
  institution: '',
  degree: '',
  field_of_study: '',
  start_year: '',
  end_year: '',
})

export const emptyProfile = (): ProfileFormValues => ({
  full_name: '',
  email: '',
  phone: '',
  city: '',
  country_code: '',
  linkedin_url: '',
  github_url: '',
  portfolio_url: '',
  headline: '',
  years_experience: '',
  skills: [],
  summary: '',
  experiences: [],
  educations: [],
  desired_roles: [],
  work_modes: [],
  open_to_relocation: '',
  notice_period_days: '',
  expected_salary: '',
  salary_currency: '',
})
