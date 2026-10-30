import { apiRequest } from '@/shared/api/client'
import type { CreateUserPayload, UserAccount, UserAccountPage } from './types'

const BASE = '/api/v1/admin/users'
export const PAGE_SIZE = 50

export function listUsers(cursor: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
  if (cursor) params.set('cursor', cursor)
  return apiRequest<UserAccountPage>(`${BASE}?${params}`, { signal })
}

export function createUser(payload: CreateUserPayload) {
  return apiRequest<UserAccount>(BASE, { method: 'POST', body: JSON.stringify(payload) })
}

export function setUserActive(id: string, isActive: boolean) {
  return apiRequest<UserAccount>(`${BASE}/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active: isActive }),
  })
}

export function resetUserPassword(id: string, temporaryPassword: string) {
  return apiRequest<UserAccount>(`${BASE}/${encodeURIComponent(id)}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ temporary_password: temporaryPassword }),
  })
}
