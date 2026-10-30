import { z } from 'zod'

export const MIN_PASSWORD_LENGTH = 12
export const MAX_PASSWORD_LENGTH = 200

export const changePasswordSchema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password.').max(MAX_PASSWORD_LENGTH),
    new_password: z
      .string()
      .min(MIN_PASSWORD_LENGTH, `Use at least ${MIN_PASSWORD_LENGTH} characters.`)
      .max(MAX_PASSWORD_LENGTH, `Use at most ${MAX_PASSWORD_LENGTH} characters.`),
    confirm_password: z.string(),
  })
  .superRefine((values, ctx) => {
    if (values.confirm_password !== values.new_password) {
      ctx.addIssue({ code: 'custom', path: ['confirm_password'], message: 'The passwords do not match.' })
    }
    if (values.new_password && values.new_password === values.current_password) {
      ctx.addIssue({
        code: 'custom',
        path: ['new_password'],
        message: 'Choose a password different from the current one.',
      })
    }
  })

export type ChangePasswordValues = z.infer<typeof changePasswordSchema>
