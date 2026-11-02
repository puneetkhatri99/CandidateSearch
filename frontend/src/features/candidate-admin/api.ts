import type { ProfilePayload } from '@/features/candidate-profile'
import { apiRequest, BASE_URL } from '@/shared/api/client'
import { streamRequest } from '@/shared/api/stream'
import {
  type BookmarkList,
  type CandidateDetail,
  type CandidatePage,
  FILTER_KEYS,
  type SavedSearchDetail,
  type SavedSearchPage,
  type SearchFilters,
  type SemanticSearchResult,
  type StageEvent,
} from './types'

const HISTORY = '/api/v1/semantic-search/history'

const BASE = '/api/v1/admin/candidates'
export const PAGE_SIZE = 25
export const SEARCH_RESULT_LIMIT = 25

function filterParams(filters: SearchFilters, limit: number) {
  const params = new URLSearchParams({ limit: String(limit) })
  for (const key of FILTER_KEYS) {
    const value = filters[key].trim()
    if (value) params.set(key, value)
  }
  return params
}

interface RunListeners {
  onStage: (event: StageEvent) => void
}

/** Hybrid search, ranked by AI, then split by the hard filters; streams each step. */
export function searchByMeaning(filters: SearchFilters, listeners: RunListeners) {
  const params = filterParams(filters, SEARCH_RESULT_LIMIT)
  return streamRequest<SemanticSearchResult, StageEvent>(`/api/v1/semantic-search/candidates/stream?${params}`, listeners)
}

/** Candidates for a job, ranked by AI against it and split by its requirements; streams each step. */
export function matchCandidatesToJob(jobId: string, listeners: RunListeners) {
  return streamRequest<SemanticSearchResult, StageEvent>(
    `/api/v1/semantic-search/jobs/${encodeURIComponent(jobId)}/candidates/stream`,
    listeners,
  )
}

/** Your own past searches, newest first. Free: nothing is re-run. */
export function listSavedSearches(cursor: string | null, signal?: AbortSignal) {
  const params = cursor ? `?${new URLSearchParams({ cursor })}` : ''
  return apiRequest<SavedSearchPage>(`${HISTORY}${params}`, { signal })
}

/** A past search with its result as it was ranked. Free: no AI call. */
export function getSavedSearch(id: string, signal?: AbortSignal) {
  return apiRequest<SavedSearchDetail>(`${HISTORY}/${encodeURIComponent(id)}`, { signal })
}

export function starSavedSearch(id: string, starred: boolean) {
  return apiRequest<void>(`${HISTORY}/${encodeURIComponent(id)}/star`, {
    method: 'PUT',
    body: JSON.stringify({ starred }),
  })
}

export function deleteSavedSearch(id: string) {
  return apiRequest<void>(`${HISTORY}/${encodeURIComponent(id)}`, { method: 'DELETE' })
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

export function createCandidate(payload: ProfilePayload & { consent_confirmed: boolean; resume_ref: string | null }) {
  return apiRequest<CandidateDetail>(BASE, { method: 'POST', body: JSON.stringify(payload) })
}

export function updateCandidate(id: string, payload: ProfilePayload & { version: number }) {
  return apiRequest<CandidateDetail>(`${BASE}/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function listBookmarks(signal?: AbortSignal) {
  return apiRequest<BookmarkList>(`${BASE}/bookmarks`, { signal })
}

export function setBookmark(id: string, bookmarked: boolean) {
  return apiRequest<void>(`${BASE}/${encodeURIComponent(id)}/bookmark`, { method: bookmarked ? 'PUT' : 'DELETE' })
}

/** Reads the file with ResumeAI and links it; the profile fields stay as they are. */
export function attachResume(id: string, file: File) {
  return apiRequest<void>(`${BASE}/${encodeURIComponent(id)}/resume`, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': 'application/octet-stream' },
  })
}

/** Opened as a plain link in a new tab: the browser shows the PDF ResumeAI renders. */
export const formattedResumeUrl = (id: string) => `${BASE_URL}${BASE}/${encodeURIComponent(id)}/resume`

export function deleteCandidate(id: string) {
  return apiRequest<void>(`${BASE}/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
