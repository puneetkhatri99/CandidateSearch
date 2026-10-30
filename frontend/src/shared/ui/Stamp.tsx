import type { ReactNode } from 'react'

export type StampTone = 'neutral' | 'brass' | 'success' | 'warning' | 'danger' | 'dangerSolid'

const TONES: Record<StampTone, string> = {
  neutral: 'bg-surface-muted text-fg-muted',
  brass: 'bg-accent-soft text-accent-soft-fg',
  success: 'bg-success-soft text-success-fg',
  warning: 'bg-warning-soft text-warning-fg',
  danger: 'bg-danger-soft text-danger-fg',
  dangerSolid: 'bg-danger-soft text-danger-fg',
}

/** A small status pill. Colour comes from the semantic tokens. */
export function Stamp({ children, tone = 'neutral' }: { children: ReactNode; tone?: StampTone }) {
  return (
    <span className={`num inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium leading-4 ${TONES[tone]}`}>
      {children}
    </span>
  )
}
