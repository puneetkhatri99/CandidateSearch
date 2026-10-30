import { COUNTRIES } from '@/shared/data/countries'
import { formatYears } from '@/shared/format'
import type { EmbeddingStatus, JobSummary } from './types'

export const formatYearRange = (minYears: number, maxYears: number | null): string =>
  maxYears === null ? `${formatYears(minYears)}+` : `${formatYears(minYears)}–${formatYears(maxYears)}`

const COUNTRY_NAMES = new Map(COUNTRIES.map((c) => [c.code, c.name]))
export const countryName = (code: string): string => COUNTRY_NAMES.get(code) ?? code

export function formatLocation(job: Pick<JobSummary, 'city' | 'country_code' | 'work_mode'>): string {
  const parts = [job.city, job.country_code && countryName(job.country_code)].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : job.work_mode === 'remote' ? 'Anywhere' : '—'
}

export const EMBEDDING_STATUS_LABELS: Record<EmbeddingStatus, string> = {
  ready: 'Ready',
  pending: 'Queued',
  failed: 'Failed',
  budget_blocked: 'Waiting for AI budget',
}
