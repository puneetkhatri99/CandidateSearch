/** Thin fetch wrapper that understands the backend's standard error body. */

export const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? ''

export interface ApiErrorBody {
  error: { code: string; message: string; details: Record<string, unknown> }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === 'object' && value !== null && 'error' in value
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    // The session cookie only travels to our own origin.
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      // CSRF guard: the API rejects state-changing staff requests without this header.
      'X-Requested-With': 'fetch',
      ...init.headers,
    },
  })

  const body: unknown = response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) throw errorFromBody(response, body)

  return body as T
}

/** The ApiError for a failed response whose body (parsed JSON, or null) has been read. */
export function errorFromBody(response: Response, body: unknown): ApiError {
  if (isApiErrorBody(body)) {
    const { code, message, details } = body.error
    return new ApiError(response.status, code, message, details)
  }
  return new ApiError(response.status, 'http_error', response.statusText)
}
