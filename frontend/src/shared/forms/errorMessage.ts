/**
 * First error message from a react-hook-form error node. Array fields can carry their error
 * on the node itself, on `.root`, or on individual items.
 */
export function errorMessage(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined
  if ('message' in error && typeof error.message === 'string' && error.message) return error.message
  if ('root' in error) {
    const fromRoot = errorMessage(error.root)
    if (fromRoot) return fromRoot
  }
  if (Array.isArray(error)) {
    for (const item of error) {
      const message = errorMessage(item)
      if (message) return message
    }
  }
  return undefined
}
