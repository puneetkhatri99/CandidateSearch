import type { JobFormValues } from './schema'
import type { JobDetail } from './types'

/** Turns a stored job into the string-based values the edit form works with. */
export function detailToFormValues(job: JobDetail): JobFormValues {
  return {
    title: job.title,
    department: job.department ?? '',
    employment_type: job.employment_type,
    status: job.status,
    work_mode: job.work_mode,
    city: job.city ?? '',
    country_code: job.country_code ?? '',
    min_years: String(job.min_years),
    max_years: job.max_years === null ? '' : String(job.max_years),
    must_have_skills: job.must_have_skills,
    nice_to_have_skills: job.nice_to_have_skills,
    description: job.description,
    salary_min: job.salary_min === null ? '' : String(job.salary_min),
    salary_max: job.salary_max === null ? '' : String(job.salary_max),
    salary_currency: job.salary_currency ?? '',
  }
}
