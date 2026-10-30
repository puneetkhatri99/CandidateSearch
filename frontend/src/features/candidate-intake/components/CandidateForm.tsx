import { zodResolver } from '@hookform/resolvers/zod'
import { FormProvider, useForm, useFormContext } from 'react-hook-form'
import { Link } from 'react-router'
import { applyProfileServerError, ProfileFields } from '@/features/candidate-profile'
import { Alert, Button, Checkbox, FormSection } from '@/shared/ui'
import { useCreateCandidate } from '../hooks/useCreateCandidate'
import { type CandidateFormValues, type CandidatePayload, candidateFormSchema, emptyCandidateForm } from '../schema'
import type { CandidateCreated } from '../types'

/**
 * Rendered after <ProfileFields /> so these fields register after the profile fields:
 * react-hook-form focuses the first invalid field in registration order.
 */
function ConsentAndHoneypot() {
  const {
    register,
    formState: { errors },
  } = useFormContext<CandidateFormValues, unknown, CandidatePayload>()
  return (
    <>
      {/* Honeypot: invisible to people and assistive tech; bots tend to fill every field. */}
      <div aria-hidden="true" className="absolute -left-[10000px] h-px w-px overflow-hidden">
        <label>
          Website
          <input tabIndex={-1} autoComplete="off" {...register('website')} />
        </label>
      </div>

      <FormSection title="Consent">
        <Checkbox
          {...register('consent')}
          error={errors.consent?.message}
          label={
            <>
              I agree that my data is stored and used for job matching, as described in the{' '}
              <Link to="/privacy" target="_blank" className="text-accent-fg underline underline-offset-4">
                privacy notice
              </Link>
              .
            </>
          }
        />
      </FormSection>
    </>
  )
}

interface CandidateFormProps {
  onSubmitted: (result: CandidateCreated) => void
  defaultValues?: Partial<CandidateFormValues>
}

export function CandidateForm({ onSubmitted, defaultValues }: CandidateFormProps) {
  const createCandidate = useCreateCandidate()
  const form = useForm<CandidateFormValues, unknown, CandidatePayload>({
    resolver: zodResolver(candidateFormSchema),
    defaultValues: { ...emptyCandidateForm(), ...defaultValues },
    mode: 'onTouched',
  })
  const {
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = form

  const onSubmit = async (payload: CandidatePayload) => {
    try {
      onSubmitted(await createCandidate.mutateAsync(payload))
    } catch (error) {
      applyProfileServerError(error, setError)
    }
  }

  return (
    <FormProvider {...form}>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="relative grid gap-10">
        <ProfileFields />
        <ConsentAndHoneypot />

        {errors.root?.server?.message && <Alert>{errors.root.server.message}</Alert>}

        <div className="flex">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Submitting…' : 'Submit profile'}
          </Button>
        </div>
      </form>
    </FormProvider>
  )
}
