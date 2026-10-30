import { Outlet } from 'react-router'
import { Alert } from '@/shared/ui'
import type { Role } from '../types'
import { useCurrentUser } from '../hooks'

/** Shows the child routes only to users with the role. The API enforces the same rule on its own. */
export function RequireRole({ role }: { role: Role }) {
  const { data: user } = useCurrentUser()
  if (user?.role !== role) {
    return (
      <div className="max-w-xl">
        <Alert>Only admins can manage staff accounts.</Alert>
      </div>
    )
  }
  return <Outlet />
}
