import { ApiError, apiRequest, BASE_URL } from '@/shared/api/client'
import type { HealthStatus, SystemDetails } from './types'

export async function fetchReadiness(signal?: AbortSignal): Promise<HealthStatus> {
  const response = await fetch(`${BASE_URL}/ready`, { signal })
  // /ready answers 503 with a valid body when a dependency is down; keep it, it says which one.
  if (response.ok || response.status === 503) return (await response.json()) as HealthStatus
  throw new ApiError(response.status, 'readiness_failed', 'The readiness check failed.')
}

export function fetchSystemDetails(signal?: AbortSignal) {
  return apiRequest<SystemDetails>('/api/v1/admin/system', { signal })
}
