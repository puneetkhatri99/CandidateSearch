import { zodResolver } from '@hookform/resolvers/zod'
import { FormProvider, useForm, useFormContext } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { z } from 'zod'
import { applyProfileServerError, candidateProfileSchema, emptyProfile, ProfileFields } from '@/features/candidate-profile'
import { Alert, Button, Checkbox, FormSection, PageHeader } from '@/shared/ui'
import { useCreateStaffCandidate } from '../hooks'

const staffCreateSchema = candidateProfileSchema.extend({
  consent_confirmed: z.boolean().refine((v) => v, 'Confirm the candidate agreed to the privacy notice.'),
})
type StaffCreateValues = z.input<typeof staffCreateSchema>
type StaffCreatePayload = z.output<typeof staffCreateSchema>

/** A child of the form so it registers after the profile fields (first-error focus order). */
function ConsentConfirmation() {
  const {
    register,
    formState: { errors },
  } = useFormContext<StaffCreateValues, unknown, StaffCreatePayload>()
  return (
    <FormSection title="Consent">
      <Checkbox
        {...register('consent_confirmed')}
        error={errors.consent_confirmed?.message}
        label={
          <>
            The candidate has agreed to the{' '}
            <Link to="/privacy" target="_blank" className="text-accent-fg underline underline-offset-4">
              privacy notice
            </Link>
            .
          </>
        }
      />
    </FormSection>
  )
}

export function CandidateCreatePage() {
  const navigate = useNavigate()
  const create = useCreateStaffCandidate()
  const form = useForm<StaffCreateValues, unknown, StaffCreatePayload>({
    resolver: zodResolver(staffCreateSchema),
    defaultValues: { ...emptyProfile(), consent_confirmed: false },
    mode: 'onTouched',
  })
  const {
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = form

  const onSubmit = async (payload: StaffCreatePayload) => {
    try {
      const created = await create.mutateAsync(payload)
      navigate(`/admin/candidates/${created.id}`, { replace: true })
    } catch (error) {
      applyProfileServerError(error, setError)
    }
  }

  return (
    <div className="grid max-w-4xl grid-cols-[minmax(0,1fr)] gap-10">
      <Link to="/admin/candidates" className="w-fit rounded-xs text-sm text-accent-fg underline-offset-4 hover:underline">
        ← Back to candidates
      </Link>
      <PageHeader title="Add candidate" />
      <FormProvider {...form}>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-10">
          <ProfileFields />
          <ConsentConfirmation />
          {errors.root?.server?.message && <Alert>{errors.root.server.message}</Alert>}
          <div className="flex gap-3">
            <Button variant="secondary" onClick={() => navigate('/admin/candidates')} disabled={isSubmitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Saving…' : 'Add candidate'}
            </Button>
          </div>
        </form>
      </FormProvider>
    </div>
  )
}
