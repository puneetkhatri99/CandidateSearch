import type { Role } from '@/features/auth'

export interface UserAccount {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
}

export interface UserAccountPage {
  items: UserAccount[]
  next_cursor: string | null
}

export interface CreateUserPayload {
  email: string
  full_name: string
  role: Role
  temporary_password: string
}
