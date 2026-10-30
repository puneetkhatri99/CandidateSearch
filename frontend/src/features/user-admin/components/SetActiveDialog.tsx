import { useState } from 'react'
import { Alert, Button } from '@/shared/ui'
import { ModalDialog } from '@/shared/ui/ModalDialog'
import { useSetUserActive } from '../hooks'
import type { UserAccount } from '../types'

function SetActiveForm({ user, onClose }: { user: UserAccount; onClose: () => void }) {
  const setActive = useSetUserActive()
  const [error, setError] = useState<string | null>(null)
  const deactivating = user.is_active

  const confirm = () => {
    setError(null)
    setActive.mutate(
      { id: user.id, isActive: !deactivating },
      { onSuccess: onClose, onError: () => setError('Could not update the account. Please try again.') },
    )
  }

  return (
    <div>
      <h2 id="set-active-title" className="text-xl font-semibold text-fg">
        {deactivating ? `Deactivate ${user.full_name}?` : `Reactivate ${user.full_name}?`}
      </h2>
      <p className="mt-2 text-sm text-fg-muted">
        {deactivating
          ? 'They are signed out immediately and cannot sign in until you reactivate the account.'
          : 'They can sign in again with their current password. Earlier sessions stay ended.'}
      </p>
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" onClick={onClose} disabled={setActive.isPending} autoFocus>
          Cancel
        </Button>
        <Button variant={deactivating ? 'dangerSolid' : 'primary'} onClick={confirm} disabled={setActive.isPending}>
          {deactivating ? 'Deactivate' : 'Reactivate'}
        </Button>
      </div>
    </div>
  )
}

export function SetActiveDialog({ user, onClose }: { user: UserAccount | null; onClose: () => void }) {
  return (
    <ModalDialog open={user !== null} labelledBy="set-active-title" onClose={onClose}>
      {user && <SetActiveForm user={user} onClose={onClose} />}
    </ModalDialog>
  )
}
