import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '@/shared/api/client'
import { changePassword, fetchCurrentUser, login, logout } from './api'

export const CURRENT_USER_KEY = ['auth', 'me'] as const

export function useCurrentUser() {
  return useQuery({ queryKey: CURRENT_USER_KEY, queryFn: fetchCurrentUser, retry: false, staleTime: 60_000 })
}

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => login(email, password),
    retry: false,
    onSuccess: (user) => queryClient.setQueryData(CURRENT_USER_KEY, user),
  })
}

export function useChangePassword() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ current, next }: { current: string; next: string }) => changePassword(current, next),
    retry: false,
    onSuccess: (user) => queryClient.setQueryData(CURRENT_USER_KEY, user),
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: logout,
    // Drop every cached query: nothing fetched with the old session may stay on screen.
    onSettled: () => {
      queryClient.clear()
      queryClient.setQueryData(CURRENT_USER_KEY, null)
    },
  })
}

/**
 * Called for every failed query and mutation. When the server says a password change is pending
 * (for example an admin reset it mid-session), refetching the current user makes RequireAuth
 * send the person to the change-password page.
 */
export function handleAuthApiError(queryClient: QueryClient, error: unknown): void {
  if (error instanceof ApiError && error.code === 'password_change_required') {
    void queryClient.invalidateQueries({ queryKey: CURRENT_USER_KEY })
  }
}
