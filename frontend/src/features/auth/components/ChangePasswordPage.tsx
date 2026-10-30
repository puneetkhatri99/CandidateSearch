import { zodResolver } from '@hookform/resolvers/zod'
import { useForm, useWatch } from 'react-hook-form'
import { useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '@/shared/api/client'
import { fieldErrorsFromApi } from '@/shared/api/validation'
import { Alert, Button, TextInput } from '@/shared/ui'
import { useChangePassword, useCurrentUser } from '../hooks'
import { safeNextPath } from '../navigation'
import { type ChangePasswordValues, changePasswordSchema, MIN_PASSWORD_LENGTH } from '../passwordSchema'

const FIELD_NAMES = ['current_password', 'new_password'] as const

export function ChangePasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { data: user } = useCurrentUser()
  const change = useChangePassword()
  const {
    register,
    handleSubmit,
    setError,
    control,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: '', new_password: '', confirm_password: '' },
    mode: 'onTouched',
  })
  const newPasswordLength = useWatch({ control, name: 'new_password' }).length

  const onSubmit = async (values: ChangePasswordValues) => {
    try {
      await change.mutateAsync({ current: values.current_password, next: values.new_password })
      navigate(safeNextPath(params.get('next')), { replace: true })
    } catch (error) {
      if (error instanceof ApiError && error.code === 'invalid_current_password') {
        setError('current_password', { message: error.message }, { shouldFocus: true })
      } else if (error instanceof ApiError && error.status === 429) {
        setError('root.server', { message: error.message })
      } else if (error instanceof ApiError && error.status === 422) {
        const fields = fieldErrorsFromApi(error).filter((e) => (FIELD_NAMES as readonly string[]).includes(e.path))
        fields.forEach((e, i) =>
          setError(e.path as (typeof FIELD_NAMES)[number], { message: e.message }, { shouldFocus: i === 0 }),
        )
        if (fields.length === 0) setError('root.server', { message: 'Check the password and try again.' })
      } else {
        setError('root.server', { message: 'Could not change the password. Please try again.' })
      }
    }
  }

  return (
    <section className="max-w-sm">
      <h1 className="text-2xl font-semibold tracking-tight text-fg">Change your password</h1>
      {user?.must_change_password && (
        <p className="mt-2 text-sm text-fg-muted">Your password was set by an admin. Choose a new one to continue.</p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 grid gap-5 border-t border-border pt-6">
        <TextInput
          label="Current password"
          type="password"
          autoComplete="current-password"
          required
          {...register('current_password')}
          error={errors.current_password?.message}
        />
        <div className="grid gap-1.5">
          <TextInput
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            {...register('new_password')}
            error={errors.new_password?.message}
          />
          <p className="num text-xs text-fg-subtle" aria-live="polite">
            {newPasswordLength}/{MIN_PASSWORD_LENGTH} minimum
          </p>
        </div>
        <TextInput
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          required
          {...register('confirm_password')}
          error={errors.confirm_password?.message}
        />
        {errors.root?.server?.message && <Alert>{errors.root.server.message}</Alert>}
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Saving…' : 'Change password'}
        </Button>
      </form>
    </section>
  )
}
