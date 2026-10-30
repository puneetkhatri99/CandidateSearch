export type MeterTone = 'ok' | 'warning' | 'danger'

const FILL: Record<MeterTone, string> = {
  ok: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger-meter',
}

interface MeterProps {
  /** 0 to 100; values outside are clamped. */
  percent: number
  tone: MeterTone
  label: string
  /** Percentage where a threshold marker is drawn. */
  markerPercent?: number
}

/** A single smooth bar with an optional threshold marker. */
export function Meter({ percent, tone, label, markerPercent }: MeterProps) {
  const clamped = Math.min(Math.max(percent, 0), 100)
  // Any non-zero spend shows at least a sliver so a tiny amount is still visible.
  const width = clamped > 0 ? Math.max(clamped, 1) : 0

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      data-tone={tone}
      className="relative h-6 py-1.5"
    >
      <div className="h-3 overflow-hidden rounded-full bg-surface-muted">
        <div className={`h-full rounded-full ${FILL[tone]}`} style={{ width: `${width}%` }} />
      </div>
      {markerPercent !== undefined && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-y-0" style={{ left: `${markerPercent}%` }}>
          <span className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-fg-muted" />
        </div>
      )}
    </div>
  )
}
