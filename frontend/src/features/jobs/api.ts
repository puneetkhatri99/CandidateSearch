import { apiRequest } from '@/shared/api/client'
import type { JobPayload } from './schema'
import type { JobDetail, JobPage, StatusFilter } from './types'

const BASE = '/api/v1/jobs'
export const PAGE_SIZE = 25

export function listJobs(status: StatusFilter, cursor: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
  if (status) params.set('status', status)
  if (cursor) params.set('cursor', cursor)
  return apiRequest<JobPage>(`${BASE}?${params}`, { signal })
}

export function getJob(id: string, signal?: AbortSignal) {
  return apiRequest<JobDetail>(`${BASE}/${encodeURIComponent(id)}`, { signal })
}

export function createJob(payload: JobPayload) {
  return apiRequest<JobDetail>(BASE, { method: 'POST', body: JSON.stringify(payload) })
}

export function updateJob(id: string, payload: Partial<JobPayload> & { version: number }) {
  return apiRequest<JobDetail>(`${BASE}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}
