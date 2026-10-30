import { ApiError } from './client'

export interface FieldError {
  /** Dotted form path, e.g. "experiences.0.end_month". Empty for whole-body errors. */
  path: string
  message: string
}

interface ServerValidationError {
  loc: Array<string | number>
  msg: string
}

function isServerValidationError(value: unknown): value is ServerValidationError {
  return typeof value === 'object' && value !== null && 'loc' in value && 'msg' in value && Array.isArray(value.loc)
}

/** Converts the backend's 422 `details.errors` into form paths (drops the leading "body"). */
export function fieldErrorsFromApi(error: ApiError): FieldError[] {
  const errors = error.details.errors
  if (!Array.isArray(errors)) return []
  return errors.filter(isServerValidationError).map((e) => ({
    path: (e.loc[0] === 'body' ? e.loc.slice(1) : e.loc).join('.'),
    message: e.msg,
  }))
}
