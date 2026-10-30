import { useEffect, useState } from 'react'
import { fetchReadiness } from '../api'

export type SystemState = 'checking' | 'online' | 'degraded' | 'offline'

const POLL_INTERVAL_MS = 30_000

export function useSystemStatus(): SystemState {
  const [state, setState] = useState<SystemState>('checking')

  useEffect(() => {
    const controller = new AbortController()

    const check = async () => {
      try {
        const result = await fetchReadiness(controller.signal)
        setState(result.status === 'ok' ? 'online' : 'degraded')
      } catch {
        if (!controller.signal.aborted) setState('offline')
      }
    }

    void check()
    const timer = setInterval(() => void check(), POLL_INTERVAL_MS)
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [])

  return state
}
