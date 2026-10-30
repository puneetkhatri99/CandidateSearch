import { Navigate, Outlet, useLocation } from 'react-router'
import { Alert } from '@/shared/ui'
import { useCurrentUser } from '../hooks'

export const CHANGE_PASSWORD_PATH = '/account/password'

/**
 * Route guard: renders child routes only for a signed-in user, else redirects to /login.
 * A user who must change a temporary password can only reach the change-password page.
 */
export function RequireAuth() {
  const location = useLocation()
  const { data: user, isPending, isError } = useCurrentUser()

  if (isPending) {
    return (
      <p className="num p-8 text-xs text-fg-subtle" role="status">
        Checking your session…
      </p>
    )
  }
  if (isError) {
    return (
      <div className="max-w-xl p-8">
        <Alert>Could not reach the server. Refresh to try again.</Alert>
      </div>
    )
  }
  const here = location.pathname + location.search
  if (!user) {
    return <Navigate to={`/login?next=${encodeURIComponent(here)}`} replace />
  }
  if (user.must_change_password && location.pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={`${CHANGE_PASSWORD_PATH}?next=${encodeURIComponent(here)}`} replace />
  }
  return <Outlet />
}
