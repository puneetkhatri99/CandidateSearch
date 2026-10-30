import { Alert, Button } from '@/shared/ui'
import { ModalDialog } from '@/shared/ui/ModalDialog'

interface CloseJobDialogProps {
  open: boolean
  jobTitle: string
  pending: boolean
  error: string | null
  onConfirm: () => void
  onClose: () => void
}

export function CloseJobDialog({ open, jobTitle, pending, error, onConfirm, onClose }: CloseJobDialogProps) {
  return (
    <ModalDialog open={open} labelledBy="close-job-title" busy={pending} onClose={onClose}>
      <h2 id="close-job-title" className="text-xl font-semibold text-fg">
        Close {jobTitle}?
      </h2>
      <p className="mt-2 text-sm text-fg-muted">It stays visible and can be reopened by editing.</p>
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
          {pending ? 'Closing…' : 'Close job'}
        </Button>
      </div>
    </ModalDialog>
  )
}
