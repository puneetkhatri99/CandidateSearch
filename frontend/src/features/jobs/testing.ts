import type { JobFormValues } from './schema'
import type { JobDetail, JobSummary } from './types'

export const jobSummary = (overrides: Partial<JobSummary> = {}): JobSummary => ({
  id: 'j-1',
  title: 'Senior Backend Engineer',
  department: 'Platform',
  status: 'open',
  work_mode: 'hybrid',
  employment_type: 'full_time',
  city: 'Berlin',
  country_code: 'DE',
  min_years: 3,
  max_years: 6,
  must_have_skills: ['python', 'postgresql'],
  salary_min: 60_000,
  salary_max: 90_000,
  salary_currency: 'EUR',
  created_by: { id: 'u-1', full_name: 'Rita Recruiter' },
  created_at: '2026-10-28T10:00:00Z',
  updated_at: '2026-10-29T10:00:00Z',
  ...overrides,
})

export const jobDetail = (overrides: Partial<JobDetail> = {}): JobDetail => ({
  ...jobSummary(),
  nice_to_have_skills: ['kubernetes'],
  description: 'You will design and run backend services that match candidates to open roles. '.repeat(2),
  version: 2,
  can_edit: true,
  embedding_status: 'pending',
  ...overrides,
})

export const validJobValues = (overrides: Partial<JobFormValues> = {}): JobFormValues => ({
  title: 'Senior Backend Engineer',
  department: 'Platform',
  employment_type: 'full_time',
  status: 'draft',
  work_mode: 'hybrid',
  city: 'Berlin',
  country_code: 'DE',
  min_years: '3',
  max_years: '6',
  must_have_skills: ['Python', 'PostgreSQL'],
  nice_to_have_skills: ['Kubernetes'],
  description: 'You will design and run backend services that match candidates to open roles. '.repeat(2),
  salary_min: '',
  salary_max: '',
  salary_currency: '',
  ...overrides,
})
