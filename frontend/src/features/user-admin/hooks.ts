import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { createUser, listUsers, resetUserPassword, setUserActive } from './api'

const USERS_KEY = ['users', 'list'] as const

export function useUsers() {
  return useInfiniteQuery({
    queryKey: USERS_KEY,
    queryFn: ({ pageParam, signal }) => listUsers(pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    retry: false,
  })
}

function useRefreshUsers() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: USERS_KEY })
}

export function useCreateUser() {
  const refresh = useRefreshUsers()
  return useMutation({ mutationFn: createUser, retry: false, onSuccess: refresh })
}

export function useSetUserActive() {
  const refresh = useRefreshUsers()
  return useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) => setUserActive(id, isActive),
    retry: false,
    onSuccess: refresh,
  })
}

export function useResetUserPassword() {
  const refresh = useRefreshUsers()
  return useMutation({
    mutationFn: ({ id, temporaryPassword }: { id: string; temporaryPassword: string }) =>
      resetUserPassword(id, temporaryPassword),
    retry: false,
    onSuccess: refresh,
  })
}
