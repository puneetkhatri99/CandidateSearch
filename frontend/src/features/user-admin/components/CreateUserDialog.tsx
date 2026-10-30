import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'
import { ApiError } from '@/shared/api/client'
import { fieldErrorsFromApi } from '@/shared/api/validation'
import { Alert, Button, SelectInput, TextInput } from '@/shared/ui'
import { ModalDialog } from '@/shared/ui/ModalDialog'
import { useCreateUser } from '../hooks'
import { generateTemporaryPassword } from '../password'
import { type CreateUserOutput, type CreateUserValues, createUserSchema, MIN_PASSWORD_LENGTH } from '../schema'
import { TemporaryPasswordField } from './TemporaryPasswordField'

const FIELDS = ['email', 'full_name', 'role', 'temporary_password'] as const

function CreateUserForm({ onClose }: { onClose: () => void }) {
  const create = useCreateUser()
  const {
    register,
    handleSubmit,
    setError,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<CreateUserValues, unknown, CreateUserOutput>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { email: '', full_name: '', role: 'recruiter', temporary_password: '' },
    mode: 'onTouched',
  })

  const onSubmit = async (values: CreateUserOutput) => {
    try {
      await create.mutateAsync(values)
      onClose()
    } catch (error) {
      if (error instanceof ApiError && error.code === 'user_exists') {
        setError('email', { message: error.message }, { shouldFocus: true })
      } else if (error instanceof ApiError && error.status === 422) {
        const fields = fieldErrorsFromApi(error).filter((e) => (FIELDS as readonly string[]).includes(e.path))
        fields.forEach((e, i) => setError(e.path as (typeof FIELDS)[number], { message: e.message }, { shouldFocus: i === 0 }))
        if (fields.length === 0) setError('root.server', { message: 'Check the details and try again.' })
      } else {
        setError('root.server', { message: 'Could not add the account. Please try again.' })
      }
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate>
      <h2 id="create-user-title" className="text-xl font-semibold text-fg">
        Add recruiter
      </h2>
      <p className="mt-2 text-sm text-fg-muted">
        They sign in with the temporary password and must choose their own before doing anything else.
      </p>
      <div className="mt-5 grid gap-5">
        <TextInput
          label="Email"
          type="email"
          autoComplete="off"
          className="num"
          required
          autoFocus
          {...register('email')}
          error={errors.email?.message}
        />
        <TextInput label="Full name" autoComplete="off" required {...register('full_name')} error={errors.full_name?.message} />
        <SelectInput label="Role" {...register('role')} error={errors.role?.message}>
          <option value="recruiter">Recruiter</option>
          <option value="admin">Admin</option>
        </SelectInput>
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
          {isSubmitting ? 'Saving…' : 'Add account'}
        </Button>
      </div>
    </form>
  )
}

export function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <ModalDialog open={open} labelledBy="create-user-title" onClose={onClose}>
      <CreateUserForm onClose={onClose} />
    </ModalDialog>
  )
}
