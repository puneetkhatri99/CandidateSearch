import { STATUS_LABELS, useSystemStatus } from '../hooks/useSystemStatus'

export function SystemStatus() {
  const { state } = useSystemStatus()
  const { text, dot } = STATUS_LABELS[state]

  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-fg-muted">
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${dot}`} />
      {text}
    </span>
  )
}
