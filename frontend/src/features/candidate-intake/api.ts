import { apiRequest } from '@/shared/api/client'
import type { CandidatePayload } from './schema'
import type { CandidateCreated } from './types'

export function createCandidate(payload: CandidatePayload): Promise<CandidateCreated> {
  return apiRequest<CandidateCreated>('/api/v1/candidates', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
