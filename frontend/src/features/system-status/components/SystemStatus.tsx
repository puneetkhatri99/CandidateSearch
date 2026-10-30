import { type SystemState, useSystemStatus } from '../hooks/useSystemStatus'

const LABELS: Record<SystemState, { text: string; dot: string }> = {
  checking: { text: 'Checking…', dot: 'bg-fg-subtle' },
  online: { text: 'API online', dot: 'bg-success' },
  degraded: { text: 'Database unavailable', dot: 'bg-warning' },
  offline: { text: 'API offline', dot: 'bg-danger-meter' },
}

export function SystemStatus() {
  const state = useSystemStatus()
  const { text, dot } = LABELS[state]

  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-fg-muted">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      {text}
    </span>
  )
}
