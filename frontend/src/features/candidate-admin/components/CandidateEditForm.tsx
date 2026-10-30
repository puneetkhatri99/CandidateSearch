import { zodResolver } from '@hookform/resolvers/zod'
import { FormProvider, useForm } from 'react-hook-form'
import {
  applyProfileServerError,
  candidateProfileSchema,
  ProfileFields,
  type ProfileFormValues,
  type ProfilePayload,
} from '@/features/candidate-profile'
import { ApiError } from '@/shared/api/client'
import { Alert, Button } from '@/shared/ui'
import { useUpdateCandidate } from '../hooks'
import { detailToFormValues } from '../mapping'
import type { CandidateDetail } from '../types'

interface CandidateEditFormProps {
  candidate: CandidateDetail
  onSaved: (updated: CandidateDetail) => void
  onCancel: () => void
  onReloadLatest: () => void
}

export function CandidateEditForm({ candidate, onSaved, onCancel, onReloadLatest }: CandidateEditFormProps) {
  const update = useUpdateCandidate(candidate.id)
  const form = useForm<ProfileFormValues, unknown, ProfilePayload>({
    resolver: zodResolver(candidateProfileSchema),
    defaultValues: detailToFormValues(candidate),
    mode: 'onTouched',
  })
  const {
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = form
  const conflict = update.error instanceof ApiError && update.error.code === 'version_conflict'

  const onSubmit = async (payload: ProfilePayload) => {
    try {
      onSaved(await update.mutateAsync({ ...payload, version: candidate.version }))
    } catch (error) {
      applyProfileServerError(error, setError)
    }
  }

  return (
    <FormProvider {...form}>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-10">
        <ProfileFields />
        {errors.root?.server?.message && (
          <Alert>
            {errors.root.server.message}
            {conflict && (
              <button type="button" className="ml-2 font-medium underline" onClick={onReloadLatest}>
                Discard my changes and reload
              </button>
            )}
          </Alert>
        )}
        <div className="flex gap-3">
          <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : 'Save changes'}
          </Button>
        </div>
      </form>
    </FormProvider>
  )
}
