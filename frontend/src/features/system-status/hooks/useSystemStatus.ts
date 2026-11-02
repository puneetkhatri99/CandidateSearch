import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { fetchReadiness, fetchSystemDetails } from '../api'

export type SystemState = 'checking' | 'online' | 'degraded' | 'offline'

export const STATUS_LABELS: Record<SystemState, { text: string; dot: string }> = {
  checking: { text: 'Checking…', dot: 'bg-fg-subtle' },
  online: { text: 'API online', dot: 'bg-success' },
  degraded: { text: 'Database unavailable', dot: 'bg-warning' },
  offline: { text: 'API offline', dot: 'bg-danger-meter' },
}

const POLL_INTERVAL_MS = 30_000

interface SystemStatusResult {
  state: SystemState
  /** Each dependency /ready checked, e.g. { database: true, pgvector: true }; empty when offline. */
  checks: Record<string, boolean>
  checkedAt: Date | null
}

export function useSystemStatus(): SystemStatusResult {
  const [result, setResult] = useState<SystemStatusResult>({ state: 'checking', checks: {}, checkedAt: null })

  useEffect(() => {
    const controller = new AbortController()

    const check = async () => {
      try {
        const health = await fetchReadiness(controller.signal)
        setResult({ state: health.status === 'ok' ? 'online' : 'degraded', checks: health.checks, checkedAt: new Date() })
      } catch {
        if (!controller.signal.aborted) setResult({ state: 'offline', checks: {}, checkedAt: new Date() })
      }
    }

    void check()
    const timer = setInterval(() => void check(), POLL_INTERVAL_MS)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [])

  return result
}

export function useSystemDetails() {
  return useQuery({
    queryKey: ['system', 'details'],
    queryFn: ({ signal }) => fetchSystemDetails(signal),
    refetchInterval: POLL_INTERVAL_MS,
    retry: false,
  })
}
