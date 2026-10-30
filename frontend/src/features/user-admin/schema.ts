/** Mirrors CreateUserRequest in backend/app/features/auth/schemas.py; change both together. */
import { z } from 'zod'

export const MIN_PASSWORD_LENGTH = 12
export const MAX_PASSWORD_LENGTH = 200

export const temporaryPasswordSchema = z
  .string()
  .min(MIN_PASSWORD_LENGTH, `Use at least ${MIN_PASSWORD_LENGTH} characters.`)
  .max(MAX_PASSWORD_LENGTH, `Use at most ${MAX_PASSWORD_LENGTH} characters.`)

export const createUserSchema = z.object({
  email: z
    .string()
    .trim()
    .max(254, 'Email must be at most 254 characters.')
    .pipe(z.email({ pattern: z.regexes.unicodeEmail, error: 'Enter a valid email address.' }))
    .transform((value) => value.toLowerCase()),
  full_name: z.string().trim().min(2, 'Name must be at least 2 characters.').max(120, 'Name must be at most 120 characters.'),
  role: z.enum(['recruiter', 'admin']),
  temporary_password: temporaryPasswordSchema,
})

export const resetPasswordSchema = z.object({ temporary_password: temporaryPasswordSchema })

export type CreateUserValues = z.input<typeof createUserSchema>
export type CreateUserOutput = z.output<typeof createUserSchema>
export type ResetPasswordValues = z.input<typeof resetPasswordSchema>
