import { ApiError, apiRequest } from '@/shared/api/client'
import type { StaffUser } from './types'

export function login(email: string, password: string): Promise<StaffUser> {
  return apiRequest<StaffUser>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
}

export function logout(): Promise<void> {
  return apiRequest<void>('/api/v1/auth/logout', { method: 'POST' })
}

export function changePassword(currentPassword: string, newPassword: string): Promise<StaffUser> {
  return apiRequest<StaffUser>('/api/v1/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
}

/** The signed-in user, or null when there is no valid session. */
export async function fetchCurrentUser(): Promise<StaffUser | null> {
  try {
    return await apiRequest<StaffUser>('/api/v1/auth/me')
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}
