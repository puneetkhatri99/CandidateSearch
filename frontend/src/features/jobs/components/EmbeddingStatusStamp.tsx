import { Stamp, type StampTone } from '@/shared/ui'
import { EMBEDDING_STATUS_LABELS } from '../format'
import type { EmbeddingStatus } from '../types'

const TONES: Record<EmbeddingStatus, StampTone> = {
  ready: 'success',
  pending: 'neutral',
  failed: 'danger',
  budget_blocked: 'warning',
}

export function EmbeddingStatusStamp({ status }: { status: EmbeddingStatus }) {
  return <Stamp tone={TONES[status]}>{EMBEDDING_STATUS_LABELS[status]}</Stamp>
}
