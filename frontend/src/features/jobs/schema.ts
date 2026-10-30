/**
 * Job role validation. Mirrors JobFields in backend/app/features/jobs/schemas.py;
 * change both together. The backend stays the source of truth.
 */
import { z } from 'zod'
import { WORK_MODES } from '@/features/candidate-profile'
import { COUNTRIES } from '@/shared/data/countries'
import { salaryCurrency, salaryCurrencyProblem, yearlySalary } from '@/shared/forms/salary'
import { tagList } from '@/shared/forms/tags'

export const EMPLOYMENT_TYPES = ['full_time', 'part_time', 'contract', 'internship'] as const
export const EMPLOYMENT_TYPE_LABELS: Record<(typeof EMPLOYMENT_TYPES)[number], string> = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  contract: 'Contract',
  internship: 'Internship',
}
export const JOB_STATUSES = ['draft', 'open', 'closed'] as const
export const JOB_STATUS_LABELS: Record<(typeof JOB_STATUSES)[number], string> = {
  draft: 'Draft',
  open: 'Open',
  closed: 'Closed',
}
export const MAX_SKILLS = 20
export const MAX_TITLE_LENGTH = 120
export const MIN_DESCRIPTION_LENGTH = 100
export const MAX_DESCRIPTION_LENGTH = 10_000

const COUNTRY_CODES = new Set(COUNTRIES.map((c) => c.code))
const YEARS_RE = /^\d{1,2}(\.\d)?$/
const YEARS_MESSAGE = 'Enter a number from 0 to 50 (at most one decimal).'

const blankToNull = (value: string) => (value === '' ? null : value)

const requiredText = (label: string, min: number, max: number) =>
  z
    .string()
    .trim()
    .min(min, min <= 1 ? `${label} is required.` : `${label} must be at least ${min} characters.`)
    .max(max, `${label} must be at most ${max} characters.`)

const optionalText = (label: string, max: number) =>
  z.string().trim().max(max, `${label} must be at most ${max} characters.`).transform(blankToNull)

const years = z
  .string()
  .trim()
  .refine((value) => YEARS_RE.test(value) && Number(value) <= 50, YEARS_MESSAGE)
  .transform(Number)

const optionalYears = z
  .string()
  .trim()
  .refine((value) => value === '' || (YEARS_RE.test(value) && Number(value) <= 50), YEARS_MESSAGE)
  .transform((value) => (value === '' ? null : Number(value)))

export const jobSchema = z
  .object({
    title: requiredText('Job title', 1, MAX_TITLE_LENGTH),
    department: optionalText('Department', 120),
    employment_type: z.enum(EMPLOYMENT_TYPES),
    status: z.enum(JOB_STATUSES),
    work_mode: z.enum(WORK_MODES),
    city: optionalText('City', 100),
    // '' is allowed here; whether a country is required depends on the work mode (below).
    country_code: z.string().refine((value) => value === '' || COUNTRY_CODES.has(value), 'Select a valid country.'),
    min_years: years,
    max_years: optionalYears,
    must_have_skills: tagList('skill', 1, MAX_SKILLS, 50),
    nice_to_have_skills: tagList('skill', 0, MAX_SKILLS, 50),
    description: requiredText('Description', MIN_DESCRIPTION_LENGTH, MAX_DESCRIPTION_LENGTH),
    salary_min: yearlySalary,
    salary_max: yearlySalary,
    salary_currency: salaryCurrency,
  })
  .superRefine((job, ctx) => {
    const issue = (path: string, message: string) => ctx.addIssue({ code: 'custom', path: [path], message })
    const onSite = job.work_mode !== 'remote'
    if (onSite && job.city === null) issue('city', 'Enter the city for a hybrid or onsite role.')
    if (job.country_code === '' && (onSite || job.city !== null)) issue('country_code', 'Select the country.')
    if (job.max_years !== null && job.max_years < job.min_years) {
      issue('max_years', 'Maximum years cannot be less than the minimum.')
    }
    if (job.nice_to_have_skills.some((skill) => job.must_have_skills.includes(skill))) {
      issue('nice_to_have_skills', "A skill can't be both must-have and nice-to-have.")
    }
    if (job.salary_min !== null && job.salary_max !== null && job.salary_max < job.salary_min) {
      issue('salary_max', 'Maximum pay cannot be less than the minimum.')
    }
    const currency = salaryCurrencyProblem(job.salary_min !== null || job.salary_max !== null, job.salary_currency)
    if (currency) issue('salary_currency', currency)
  })
  .transform((job) => ({ ...job, country_code: blankToNull(job.country_code) }))

export type JobFormValues = z.input<typeof jobSchema>
export type JobPayload = z.output<typeof jobSchema>

export const emptyJob = (): JobFormValues => ({
  title: '',
  department: '',
  employment_type: 'full_time',
  status: 'draft',
  work_mode: 'hybrid',
  city: '',
  country_code: '',
  min_years: '',
  max_years: '',
  must_have_skills: [],
  nice_to_have_skills: [],
  description: '',
  salary_min: '',
  salary_max: '',
  salary_currency: '',
})
