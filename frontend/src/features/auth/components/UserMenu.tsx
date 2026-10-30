import { Link, useNavigate } from 'react-router'
import { Button, Stamp } from '@/shared/ui'
import { useCurrentUser, useLogout } from '../hooks'

/** `stacked` lays the name, role and sign-out out for the sidebar; the default is one inline row. */
export function UserMenu({ stacked = false }: { stacked?: boolean }) {
  const navigate = useNavigate()
  const { data: user } = useCurrentUser()
  const logoutMutation = useLogout()

  if (!user) {
    return (
      <Link to="/login" className="rounded-xs text-sm font-medium text-accent-fg underline-offset-4 hover:underline">
        Staff sign in
      </Link>
    )
  }

  return (
    <div className={`flex gap-x-3 gap-y-2 text-sm ${stacked ? 'flex-wrap items-center md:flex-col md:items-start' : 'flex-wrap items-center'}`}>
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-fg">{user.full_name}</span>
        <Stamp tone="brass">{user.role}</Stamp>
      </span>
      <Link to="/account/password" className="rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline">
        Change password
      </Link>
      <Button
        variant="secondary"
        size="sm"
        disabled={logoutMutation.isPending}
        onClick={() => logoutMutation.mutate(undefined, { onSettled: () => navigate('/login') })}
      >
        Sign out
      </Button>
    </div>
  )
}
