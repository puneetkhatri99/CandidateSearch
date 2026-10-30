/** Mirrors the staff candidate schemas in backend/app/features/candidates/schemas.py. */

export interface CandidateSummary {
  id: string
  full_name: string
  email: string
  headline: string
  city: string
  country_code: string
  years_experience: number
  top_skills: string[]
  /** Yearly, in whole units of salary_currency; both null when not stated. */
  expected_salary: number | null
  salary_currency: string | null
  source: string
  created_at: string
}

export interface CandidatePage {
  items: CandidateSummary[]
  next_cursor: string | null
}

/** Mirrors backend/app/features/semantic_search/schemas.py. */
export interface Criterion {
  name: 'skills' | 'location' | 'experience' | 'salary'
  status: 'met' | 'partial' | 'missed'
  note: string
}

export interface SemanticMatch {
  candidate: CandidateSummary
  /** null, with no criteria, when the AI ranking was unavailable. */
  fit: 'strong' | 'partial' | 'weak' | null
  criteria: Criterion[]
  /** The hard filters this candidate fails; empty for everyone in `items`. */
  failed_filters: FilterName[]
}

/** One streamed step of a search; mirrors StageEvent in semantic_search/schemas.py. */
export const STAGES = ['embedding', 'retrieval', 'augmentation', 'ranking', 'filtering'] as const
export type Stage = (typeof STAGES)[number]

export interface StageEvent {
  stage: Stage
  state: 'started' | 'done'
  detail: string | null
  elapsed_ms: number | null
}

export interface SemanticSearchResult {
  /** Best first; these pass every hard filter. */
  items: SemanticMatch[]
  /** The other search hits, in the same ranked order. */
  filtered_out: SemanticMatch[]
  /** "search": the AI ranking was unavailable, so results are in hybrid-search order. */
  ranked_by: 'ai' | 'search'
  embedding_model: string
  ranking_model: string | null
  prompt_version: string | null
}

export interface ExperienceDetail {
  company: string
  title: string
  start_month: string
  is_current: boolean
  end_month: string | null
  description: string | null
}

export interface EducationDetail {
  institution: string
  degree: string | null
  field_of_study: string | null
  start_year: number | null
  end_year: number | null
}

export interface CandidateDetail {
  id: string
  version: number
  full_name: string
  email: string
  phone: string | null
  city: string
  country_code: string
  linkedin_url: string | null
  github_url: string | null
  portfolio_url: string | null
  headline: string
  years_experience: number
  skills: string[]
  summary: string
  experiences: ExperienceDetail[]
  educations: EducationDetail[]
  desired_roles: string[]
  work_modes: string[]
  open_to_relocation: boolean | null
  notice_period_days: number | null
  /** Yearly, in whole units of salary_currency; both null when not stated. */
  expected_salary: number | null
  salary_currency: string | null
  source: string
  consent_given_at: string
  consent_version: string
  created_at: string
  updated_at: string
}

/** Hard filters; the same names on the candidate list and the search endpoint. */
export const FILTER_NAMES = ['min_years', 'skill', 'city', 'country', 'source'] as const
export type FilterName = (typeof FILTER_NAMES)[number]
export const FILTER_LABELS: Record<FilterName, string> = {
  min_years: 'Min years',
  skill: 'Skills',
  city: 'City',
  country: 'Country',
  source: 'Source',
}

/** Search state as strings, exactly as it lives in the URL; '' means "not set". */
export type SearchFilters = Record<'q' | FilterName, string>

export const FILTER_KEYS = ['q', ...FILTER_NAMES] as const
