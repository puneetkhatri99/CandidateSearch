import { vi } from 'vitest'

export interface FakeResponse {
  status?: number
  body?: unknown
  /** A raw text/event-stream body instead of JSON (see sseBody). */
  stream?: string
}

/** Formats server-sent events the way the API sends them. */
export const sseBody = (...events: [name: string, data: unknown][]) =>
  events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join('')

type Handler = (url: URL, init: RequestInit) => FakeResponse | undefined

/** Stubs fetch with route handlers; the first handler returning a response wins. Unmatched → 404. */
export function stubApi(...handlers: Handler[]) {
  const fetchMock = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, 'http://localhost')
    for (const handler of handlers) {
      const result = handler(url, init)
      if (result) {
        const status = result.status ?? 200
        if (result.stream !== undefined) {
          return new Response(result.stream, { status, headers: { 'Content-Type': 'text/event-stream' } })
        }
        return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), {
          status,
          headers: { 'Content-Type': 'application/json' },
        })
      }
    }
    return new Response(JSON.stringify({ error: { code: 'not_found', message: 'Not found', details: {} } }), {
      status: 404,
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The /auth/me body for a signed-in user; fixtures carry the password-change flag explicitly. */
export const staffUser = (overrides: Record<string, unknown> = {}) => ({
  id: 'u-1',
  email: 'staff@example.com',
  full_name: 'Staff Member',
  role: 'recruiter',
  must_change_password: false,
  ...overrides,
})

export const route =
  (method: string, path: string | RegExp, response: FakeResponse | ((url: URL, init: RequestInit) => FakeResponse)): Handler =>
  (url, init) => {
    const matches = typeof path === 'string' ? url.pathname === path : path.test(url.pathname)
    if (!matches || (init.method ?? 'GET') !== method) return undefined
    return typeof response === 'function' ? response(url, init) : response
  }
