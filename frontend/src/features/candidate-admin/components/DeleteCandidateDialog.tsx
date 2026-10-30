import { useEffect, useRef } from 'react'
import { Alert, Button } from '@/shared/ui'

interface DeleteCandidateDialogProps {
  open: boolean
  candidateName: string
  pending: boolean
  error: string | null
  onConfirm: () => void
  onClose: () => void
}

/** Native <dialog>: showModal() traps focus, Escape cancels, focus returns to the opener on close. */
export function DeleteCandidateDialog({ open, candidateName, pending, error, onConfirm, onClose }: DeleteCandidateDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="delete-candidate-title"
      onCancel={(e) => {
        e.preventDefault()
        if (!pending) onClose()
      }}
      className="m-auto w-full max-w-[min(28rem,calc(100%-2rem))] rounded-md border border-border bg-surface-raised p-8 text-fg shadow-xl backdrop:bg-black/50"
    >
      <h2 id="delete-candidate-title" className="text-xl font-semibold text-fg">
        Delete {candidateName}?
      </h2>
      <p className="mt-2 text-sm text-fg-muted">
        This permanently removes the profile, work history and education. It cannot be undone.
      </p>
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" onClick={onClose} disabled={pending} autoFocus>
          Cancel
        </Button>
        <Button variant="dangerSolid" onClick={onConfirm} disabled={pending}>
          {pending ? 'Deleting…' : 'Delete permanently'}
        </Button>
      </div>
    </dialog>
  )
}
