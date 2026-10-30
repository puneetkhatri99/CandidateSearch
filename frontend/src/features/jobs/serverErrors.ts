import type { FieldPath, UseFormSetError } from 'react-hook-form'
import { ApiError } from '@/shared/api/client'
import { fieldErrorsFromApi } from '@/shared/api/validation'
import type { JobFormValues } from './schema'

export const CONFLICT_MESSAGE = 'This job was changed by someone else. Reload to see the latest version.'

const FIELD_NAMES: ReadonlySet<string> = new Set([
  'title',
  'department',
  'employment_type',
  'status',
  'work_mode',
  'city',
  'country_code',
  'min_years',
  'max_years',
  'must_have_skills',
  'nice_to_have_skills',
  'description',
])
// Tag lists carry their list-level error on `.root` in react-hook-form.
const LIST_FIELDS: ReadonlySet<string> = new Set(['must_have_skills', 'nice_to_have_skills'])

export function isVersionConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && error.code === 'version_conflict'
}

/** Puts an API error from a job save onto the right fields, or the form root. */
export function applyJobServerError(error: unknown, setError: UseFormSetError<JobFormValues>) {
  const setRoot = (message: string) => setError('root.server', { message })

  if (isVersionConflict(error)) {
    setRoot(CONFLICT_MESSAGE)
    return
  }
  if (error instanceof ApiError && error.status === 422) {
    const fieldErrors = fieldErrorsFromApi(error).filter((e) => FIELD_NAMES.has(e.path))
    fieldErrors.forEach((e, index) =>
      setError(
        (LIST_FIELDS.has(e.path) ? `${e.path}.root` : e.path) as FieldPath<JobFormValues>,
        { message: e.message },
        { shouldFocus: index === 0 },
      ),
    )
    if (fieldErrors.length > 0) {
      setRoot('Please fix the highlighted fields.')
      return
    }
  }
  if (error instanceof ApiError && error.status === 403) {
    setRoot(error.message)
    return
  }
  setRoot('Something went wrong while saving. Please try again.')
}
