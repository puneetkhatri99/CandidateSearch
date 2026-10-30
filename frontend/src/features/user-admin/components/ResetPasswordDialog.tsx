import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { Alert, Button } from '@/shared/ui'
import { ModalDialog } from '@/shared/ui/ModalDialog'
import { useResetUserPassword } from '../hooks'
import { generateTemporaryPassword } from '../password'
import { MIN_PASSWORD_LENGTH, type ResetPasswordValues, resetPasswordSchema } from '../schema'
import type { UserAccount } from '../types'
import { TemporaryPasswordField } from './TemporaryPasswordField'

function ResetPasswordForm({ user, onClose }: { user: UserAccount; onClose: () => void }) {
  const reset = useResetUserPassword()
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordValues>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { temporary_password: '' },
    mode: 'onTouched',
  })

  const onSubmit = async (values: ResetPasswordValues) => {
    try {
      await reset.mutateAsync({ id: user.id, temporaryPassword: values.temporary_password })
      onClose()
    } catch {
      setError('root.server', { message: 'Could not reset the password. Please try again.' })
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate>
      <h2 id="reset-password-title" className="text-xl font-semibold text-fg">
        Reset password for {user.full_name}
      </h2>
      <p className="mt-2 text-sm text-fg-muted">
        They are signed out everywhere now and must choose a new password the next time they sign in.
      </p>
      <div className="mt-5 grid gap-5">
        <TemporaryPasswordField
          inputProps={register('temporary_password')}
          error={errors.temporary_password?.message}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters. Copy it before saving: it is not shown again.`}
          onGenerate={() => setValue('temporary_password', generateTemporaryPassword(), { shouldValidate: true })}
          getValue={() => getValues('temporary_password')}
        />
        {errors.root?.server?.message && <Alert>{errors.root.server.message}</Alert>}
      </div>
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Resetting…' : 'Reset password'}
        </Button>
      </div>
    </form>
  )
}

export function ResetPasswordDialog({ user, onClose }: { user: UserAccount | null; onClose: () => void }) {
  return (
    <ModalDialog open={user !== null} labelledBy="reset-password-title" onClose={onClose}>
      {user && <ResetPasswordForm user={user} onClose={onClose} />}
    </ModalDialog>
  )
}
