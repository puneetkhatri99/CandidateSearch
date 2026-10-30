import { describe, expect, it } from 'vitest'
import { GENERATED_PASSWORD_LENGTH, generateTemporaryPassword } from './password'

describe('generateTemporaryPassword', () => {
  it('is 16 characters, long enough for the 12-character minimum', () => {
    expect(generateTemporaryPassword()).toHaveLength(GENERATED_PASSWORD_LENGTH)
    expect(GENERATED_PASSWORD_LENGTH).toBeGreaterThanOrEqual(12)
  })

  it('avoids look-alike characters', () => {
    const sample = Array.from({ length: 200 }, generateTemporaryPassword).join('')
    expect(sample).toMatch(/^[A-HJ-NP-Za-km-z2-9]+$/)
  })

  it('does not repeat', () => {
    const passwords = new Set(Array.from({ length: 100 }, generateTemporaryPassword))
    expect(passwords.size).toBe(100)
  })
})
