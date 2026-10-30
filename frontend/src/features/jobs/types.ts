export type JobStatus = 'draft' | 'open' | 'closed'
export type JobWorkMode = 'remote' | 'hybrid' | 'onsite'
export type EmploymentType = 'full_time' | 'part_time' | 'contract' | 'internship'
export type EmbeddingStatus = 'ready' | 'pending' | 'failed' | 'budget_blocked'

export interface JobOwner {
  id: string
  full_name: string
}

export interface JobSummary {
  id: string
  title: string
  department: string | null
  status: JobStatus
  work_mode: JobWorkMode
  employment_type: EmploymentType
  city: string | null
  country_code: string | null
  min_years: number
  max_years: number | null
  must_have_skills: string[]
  /** Yearly pay range in whole units of salary_currency; either end may be open. */
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  created_by: JobOwner
  created_at: string
  updated_at: string
}

export interface JobDetail extends JobSummary {
  nice_to_have_skills: string[]
  description: string
  version: number
  can_edit: boolean
  embedding_status: EmbeddingStatus
}

export interface JobPage {
  items: JobSummary[]
  next_cursor: string | null
}

export type StatusFilter = JobStatus | ''
