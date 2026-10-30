export type Role = 'admin' | 'recruiter'

export interface StaffUser {
  id: string
  email: string
  full_name: string
  role: Role
  /** True while an admin-chosen temporary password is still in use; the API refuses everything else. */
  must_change_password: boolean
}
