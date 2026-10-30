import type { FieldPath, FieldValues, UseFormSetError } from 'react-hook-form'
import { ApiError } from '@/shared/api/client'
import { fieldErrorsFromApi } from '@/shared/api/validation'

// Array fields carry list-level errors on `.root` in react-hook-form.
const ARRAY_FIELDS = new Set(['experiences', 'educations', 'skills', 'desired_roles', 'work_modes'])

/** Puts an API error from a profile save onto the right form fields, or the form root. */
export function applyProfileServerError<T extends FieldValues>(error: unknown, setError: UseFormSetError<T>) {
  const setRoot = (message: string) => setError('root.server', { message })
  const setField = (path: string, message: string, focus: boolean) =>
    setError(path as FieldPath<T>, { message }, { shouldFocus: focus })

  if (error instanceof ApiError) {
    if (error.status === 409 && error.code === 'candidate_exists') {
      setField('email', error.message, true)
      return
    }
    if (error.status === 409 && error.code === 'version_conflict') {
      setRoot(error.message)
      return
    }
    if (error.status === 422) {
      const fieldErrors = fieldErrorsFromApi(error).filter((e) => e.path)
      fieldErrors.forEach((e, i) => setField(ARRAY_FIELDS.has(e.path) ? `${e.path}.root` : e.path, e.message, i === 0))
      if (fieldErrors.length > 0) {
        setRoot('Please fix the highlighted fields.')
        return
      }
    }
    if (error.status === 429) {
      setRoot('Too many submissions from your network. Please try again later.')
      return
    }
    if (error.status === 401) {
      setRoot('Your session has ended. Sign in again, then retry.')
      return
    }
  }
  setRoot('Something went wrong while saving. Please try again.')
}
