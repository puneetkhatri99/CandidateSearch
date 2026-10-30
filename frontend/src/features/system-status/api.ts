import { ApiError, apiRequest } from '@/shared/api/client'
import type { HealthStatus } from './types'

export async function fetchReadiness(signal?: AbortSignal): Promise<HealthStatus> {
  try {
    return await apiRequest<HealthStatus>('/ready', { signal })
  } catch (error) {
    // /ready answers 503 with a valid body when a dependency is down.
    if (error instanceof ApiError && error.status === 503) {
      return { status: 'unavailable', checks: {} }
    }
    throw error
  }
}
