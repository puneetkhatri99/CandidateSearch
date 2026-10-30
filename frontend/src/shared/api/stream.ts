/**
 * Reads a server-sent-events response: `stage` events go to `onStage` as they arrive, then
 * the `result` event resolves the promise and an `error` event rejects it with an ApiError.
 * fetch is used instead of EventSource so the request carries the CSRF header and an abort
 * signal like every other API call.
 */
import { ApiError, BASE_URL, errorFromBody } from './client'

interface StreamError {
  status: number
  code: string
  message: string
}

function parseBlock(block: string): { name: string; data: unknown } | null {
  let name = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  return data.length ? { name, data: JSON.parse(data.join('\n')) } : null
}

export async function streamRequest<TResult, TStage>(
  path: string,
  { signal, onStage }: { signal?: AbortSignal; onStage: (stage: TStage) => void },
): Promise<TResult> {
  const response = await fetch(`${BASE_URL}${path}`, {
    signal,
    credentials: 'same-origin',
    headers: { Accept: 'text/event-stream', 'X-Requested-With': 'fetch' },
  })
  // Errors before the stream starts (validation, auth) come back as the usual JSON body.
  if (!response.ok || !response.body) {
    throw errorFromBody(response, await response.json().catch(() => null))
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value.replace(/\r\n/g, '\n')
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const event = parseBlock(buffer.slice(0, end))
      buffer = buffer.slice(end + 2)
      if (!event) continue
      if (event.name === 'stage') onStage(event.data as TStage)
      else if (event.name === 'result') return event.data as TResult
      else if (event.name === 'error') {
        const error = event.data as StreamError
        throw new ApiError(error.status, error.code, error.message)
      }
    }
  }
  throw new ApiError(0, 'stream_ended', 'The connection closed before the search finished. Please try again.')
}
