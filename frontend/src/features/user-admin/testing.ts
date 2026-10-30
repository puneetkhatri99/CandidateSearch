import type { UserAccount } from './types'

export const userAccount = (overrides: Partial<UserAccount> = {}): UserAccount => ({
  id: 'u-2',
  email: 'rita@example.com',
  full_name: 'Rita Recruiter',
  role: 'recruiter',
  is_active: true,
  must_change_password: false,
  last_login_at: '2026-10-28T09:30:00Z',
  created_at: '2026-10-20T10:00:00Z',
  ...overrides,
})
