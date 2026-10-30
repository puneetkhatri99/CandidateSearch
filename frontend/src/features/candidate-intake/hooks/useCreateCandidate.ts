import { useMutation } from '@tanstack/react-query'
import { createCandidate } from '../api'

export function useCreateCandidate() {
  // A submission is not idempotent from the user's point of view; never auto-retry it.
  return useMutation({ mutationFn: createCandidate, retry: false })
}
