import { describe, expect, it } from 'vitest'
import { formatYears } from './format'

describe('formatYears', () => {
  it('pads to two integer digits with one decimal', () => {
    expect(formatYears(6.5)).toBe('06.5')
    expect(formatYears(0)).toBe('00.0')
    expect(formatYears(12)).toBe('12.0')
  })
})
