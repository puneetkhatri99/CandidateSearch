import { apiRequest } from '@/shared/api/client'
import { type BudgetSummary, type EventFilters, FILTER_KEYS, type UsageEventPage } from './types'

const BASE = '/api/v1/ai-usage'
export const PAGE_SIZE = 25

export function getSummary(signal?: AbortSignal) {
  return apiRequest<BudgetSummary>(`${BASE}/summary`, { signal })
}

export function getEvents(filters: EventFilters, cursor: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
  for (const key of FILTER_KEYS) {
    if (filters[key]) params.set(key, filters[key])
  }
  if (cursor) params.set('cursor', cursor)
  return apiRequest<UsageEventPage>(`${BASE}/events?${params}`, { signal })
}

export function updateBudget(limitUsd: string) {
  return apiRequest<BudgetSummary>(`${BASE}/budget`, { method: 'PUT', body: JSON.stringify({ limit_usd: limitUsd }) })
}