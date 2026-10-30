import type { ProfilePayload } from '@/features/candidate-profile'
import { apiRequest } from '@/shared/api/client'
import { streamRequest } from '@/shared/api/stream'
import {
  type CandidateDetail,
  type CandidatePage,
  FILTER_KEYS,
  type SearchFilters,
  type SemanticSearchResult,
  type StageEvent,
} from './types'

const BASE = '/api/v1/admin/candidates'
export const PAGE_SIZE = 25
export const SEARCH_RESULT_LIMIT = 20

function filterParams(filters: SearchFilters, limit: number) {
  const params = new URLSearchParams({ limit: String(limit) })
  for (const key of FILTER_KEYS) {
    const value = filters[key].trim()
    if (value) params.set(key, value)
  }
  return params
}

type OnStage = (event: StageEvent) => void

/** Hybrid search, ranked by AI, then split by the hard filters; streams each step. */
export function searchByMeaning(filters: SearchFilters, signal: AbortSignal, onStage: OnStage) {
  const params = filterParams(filters, SEARCH_RESULT_LIMIT)
  return streamRequest<SemanticSearchResult, StageEvent>(`/api/v1/semantic-search/candidates/stream?${params}`, {
    signal,
    onStage,
  })
}

/** Candidates for a job, ranked by AI against it and split by its requirements; streams each step. */
export function matchCandidatesToJob(jobId: string, signal: AbortSignal, onStage: OnStage) {
  return streamRequest<SemanticSearchResult, StageEvent>(
    `/api/v1/semantic-search/jobs/${encodeURIComponent(jobId)}/candidates/stream`,
    { signal, onStage },
  )
}

/** Newest first, filtered; used when there is no search text. */
export function searchCandidates(filters: SearchFilters, cursor: string | null, signal?: AbortSignal) {
  const params = filterParams({ ...filters, q: '' }, PAGE_SIZE)
  if (cursor) params.set('cursor', cursor)
  return apiRequest<CandidatePage>(`${BASE}?${params}`, { signal })
}

export function getCandidate(id: string, signal?: AbortSignal) {
  return apiRequest<CandidateDetail>(`${BASE}/${encodeURIComponent(id)}`, { signal })
}

export function createCandidate(payload: ProfilePayload & { consent_confirmed: boolean }) {
  return apiRequest<CandidateDetail>(BASE, { method: 'POST', body: JSON.stringify(payload) })
}

export function updateCandidate(id: string, payload: ProfilePayload & { version: number }) {
  return apiRequest<CandidateDetail>(`${BASE}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteCandidate(id: string) {
  return apiRequest<void>(`${BASE}/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
