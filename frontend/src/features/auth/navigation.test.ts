import { describe, expect, it } from 'vitest'
import { safeNextPath } from './navigation'

describe('safeNextPath', () => {
  it('keeps same-site paths', () => {
    expect(safeNextPath('/admin/candidates/123?x=1')).toBe('/admin/candidates/123?x=1')
  })

  it.each([null, '', 'https://evil.example', '//evil.example', '/\\evil.example', 'javascript:alert(1)'])(
    'falls back for %s',
    (next) => {
      expect(safeNextPath(next)).toBe('/admin/candidates')
    },
  )
})
