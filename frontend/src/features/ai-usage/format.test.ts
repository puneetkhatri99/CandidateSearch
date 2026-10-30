import { describe, expect, it } from 'vitest'
import { budgetTone, formatUsd } from './format'

describe('formatUsd', () => {
  it.each([
    ['0', '$0.00'],
    ['5.00', '$5.00'],
    ['12.5', '$12.50'],
    ['0.5', '$0.50'],
    ['0.012300', '$0.0123'],
    ['0.01', '$0.01'],
    ['0.0120', '$0.012'],
    ['0.00004', '<$0.0001'],
  ])('formats %s as %s', (input, expected) => {
    expect(formatUsd(input)).toBe(expected)
  })

  it('does not show tiny nonzero costs as $0.00', () => {
    expect(formatUsd('0.000064')).not.toBe('$0.00')
  })
})

describe('budgetTone', () => {
  it('is ok below 80%', () => expect(budgetTone(79.9, false)).toBe('ok'))
  it('warns at 80% and above', () => expect(budgetTone(80, false)).toBe('warning'))
  it('is danger at 100%', () => expect(budgetTone(100, false)).toBe('danger'))
  // A $0 limit reports 100% as reached even though nothing was spent.
  it('is danger when the limit is reached, whatever the percentage', () => expect(budgetTone(0, true)).toBe('danger'))
})