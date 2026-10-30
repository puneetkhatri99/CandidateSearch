import { useState } from 'react'
import { useCurrentUser } from '@/features/auth'
import { Alert, Button, PageHeader, Stamp } from '@/shared/ui'
import { useUsers } from '../hooks'
import type { UserAccount } from '../types'
import { CreateUserDialog } from './CreateUserDialog'
import { ResetPasswordDialog } from './ResetPasswordDialog'
import { SetActiveDialog } from './SetActiveDialog'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const COLUMNS = ['Name', 'Email', 'Role', 'Status', 'Last sign-in', 'Added', 'Actions']
const cell = 'px-3 py-4 align-top'
const actionClass = 'rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline'

function UserRow({
  user,
  isSelf,
  onReset,
  onToggle,
}: {
  user: UserAccount
  isSelf: boolean
  onReset: (user: UserAccount) => void
  onToggle: (user: UserAccount) => void
}) {
  return (
    <tr className="transition-colors hover:bg-surface-muted">
      <td className={`${cell} font-medium text-fg`}>{user.full_name}</td>
      <td className={`${cell} num text-data text-fg-muted`}>{user.email}</td>
      <td className={cell}>
        <Stamp tone={user.role === 'admin' ? 'brass' : 'neutral'}>{user.role}</Stamp>
      </td>
      <td className={cell}>
        <div className="flex flex-wrap gap-1">
          <Stamp tone={user.is_active ? 'success' : 'neutral'}>{user.is_active ? 'Active' : 'Inactive'}</Stamp>
          {user.must_change_password && <Stamp tone="warning">Must change password</Stamp>}
        </div>
      </td>
      <td className={`${cell} num whitespace-nowrap text-data text-fg-muted`}>
        {user.last_login_at ? dateTimeFormat.format(new Date(user.last_login_at)) : 'Never'}
      </td>
      <td className={`${cell} num whitespace-nowrap text-data text-fg-muted`}>{dateFormat.format(new Date(user.created_at))}</td>
      <td className={`${cell} whitespace-nowrap`}>
        {isSelf ? (
          <span className="text-sm text-fg-subtle">This is you</span>
        ) : (
          <div className="flex gap-4">
            <button type="button" className={actionClass} onClick={() => onReset(user)} aria-label={`Reset password for ${user.full_name}`}>
              Reset password
            </button>
            <button
              type="button"
              className={user.is_active ? 'rounded-xs font-medium text-danger-fg underline-offset-4 hover:underline' : actionClass}
              onClick={() => onToggle(user)}
              aria-label={`${user.is_active ? 'Deactivate' : 'Reactivate'} ${user.full_name}`}
            >
              {user.is_active ? 'Deactivate' : 'Reactivate'}
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

export function UserListPage() {
  const { data: me } = useCurrentUser()
  const users = useUsers()
  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<UserAccount | null>(null)
  const [toggling, setToggling] = useState<UserAccount | null>(null)
  const accounts = users.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Staff accounts"
        meta={accounts.length > 0 && <p aria-live="polite">Showing {accounts.length}</p>}
        actions={<Button onClick={() => setCreating(true)}>Add recruiter</Button>}
      />

      {users.isError ? (
        <Alert>{users.error.message || 'Could not load the accounts. Please try again.'}</Alert>
      ) : users.isPending ? (
        <p role="status" className="text-sm text-fg-muted">
          Loading accounts…
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left">
              <caption className="sr-only">Staff accounts</caption>
              <thead className="border-b border-border text-fg-muted">
                <tr>
                  {COLUMNS.map((column) => (
                    <th key={column} scope="col" className="whitespace-nowrap px-3 py-3 text-sm font-medium">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {accounts.map((user) => (
                  <UserRow key={user.id} user={user} isSelf={user.id === me?.id} onReset={setResetting} onToggle={setToggling} />
                ))}
              </tbody>
            </table>
          </div>
          {users.hasNextPage && (
            <div>
              <Button variant="secondary" onClick={() => void users.fetchNextPage()} disabled={users.isFetchingNextPage}>
                {users.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      )}

      <CreateUserDialog open={creating} onClose={() => setCreating(false)} />
      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      <SetActiveDialog user={toggling} onClose={() => setToggling(null)} />
    </div>
  )
}
