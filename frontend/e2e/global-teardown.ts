import { deleteE2eCandidates } from './support/backend.ts'

export default function globalTeardown() {
  const result = deleteE2eCandidates()
  console.log(`e2e cleanup: ${result}`)
}
