import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/shared/api/client'
import { createQueryClient } from './queryClient'

const failWith = (error: Error) => () => Promise.reject(error)

describe('createQueryClient', () => {
  it('refetches the current user when any query reports a pending password change', async () => {
    const client = createQueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')

    await client
      .fetchQuery({
        queryKey: ['jobs', 'list'],
        queryFn: failWith(new ApiError(403, 'password_change_required', 'Change your password to continue.')),
        retry: false,
      })
      .catch(() => undefined)

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['auth', 'me'] })
  })

  it('does the same for a failed mutation', async () => {
    const client = createQueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')

    await client
      .getMutationCache()
      .build(client, { mutationFn: failWith(new ApiError(403, 'password_change_required', 'x')) })
      .execute(undefined)
      .catch(() => undefined)

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['auth', 'me'] })
  })

  it('leaves other errors alone', async () => {
    const client = createQueryClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')

    await client
      .fetchQuery({
        queryKey: ['jobs', 'list'],
        queryFn: failWith(new ApiError(403, 'forbidden', 'No')),
        retry: false,
      })
      .catch(() => undefined)

    expect(invalidate).not.toHaveBeenCalled()
  })
})
