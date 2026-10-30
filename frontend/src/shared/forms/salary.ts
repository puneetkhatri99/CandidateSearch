/**
 * Yearly salary fields, shared by the candidate profile and the job form. Mirrors YearlySalary,
 * Currency and salary_needs_currency in backend/app/shared/validation.py.
 */
import { z } from 'zod'

/** The currencies offered in forms; the API accepts any ISO 4217 code. */
export const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED', 'SGD', 'CAD', 'AUD'] as const
const MAX_SALARY = 1_000_000_000

/** A whole yearly amount typed as text; '' means "not stated", and commas or spaces are ignored. */
export const yearlySalary = z
  .string()
  .trim()
  .transform((value, ctx) => {
    if (value === '') return null
    const digits = value.replace(/[,\s_]/g, '')
    const amount = Number(digits)
    if (!/^\d+$/.test(digits) || amount < 1 || amount > MAX_SALARY) {
      ctx.addIssue({ code: 'custom', message: 'Enter a whole yearly amount, e.g. 1800000.' })
      return z.NEVER
    }
    return amount
  })

export const salaryCurrency = z
  .string()
  .refine((value) => value === '' || (CURRENCIES as readonly string[]).includes(value), 'Select a valid currency.')
  .transform((value) => (value === '' ? null : value))

/** Same wording as the backend: a salary and its currency come together or not at all. */
export function salaryCurrencyProblem(hasAmount: boolean, currency: string | null): string | null {
  if (hasAmount && currency === null) return 'Select the currency.'
  if (!hasAmount && currency !== null) return 'Enter the salary, or clear the currency.'
  return null
}
