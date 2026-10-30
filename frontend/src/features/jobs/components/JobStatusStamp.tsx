import { Stamp, type StampTone } from '@/shared/ui'
import { JOB_STATUS_LABELS } from '../schema'
import type { JobStatus } from '../types'

const TONES: Record<JobStatus, StampTone> = { draft: 'neutral', open: 'success', closed: 'warning' }

export function JobStatusStamp({ status }: { status: JobStatus }) {
  return <Stamp tone={TONES[status]}>{JOB_STATUS_LABELS[status]}</Stamp>
}
