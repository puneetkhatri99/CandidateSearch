import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  // The Candidates page remembers the last search here; one test's search must not reopen in the next.
  window.localStorage.clear()
})
