import { type ReactNode, useEffect, useRef } from 'react'

interface ModalDialogProps {
  open: boolean
  /** id of the heading inside the dialog; it becomes the dialog's accessible name. */
  labelledBy: string
  /** While true, Escape does not close the dialog (a request is in flight). */
  busy?: boolean
  onClose: () => void
  children: ReactNode
}

/** Native <dialog>: showModal() traps focus, Escape cancels, focus returns to the opener on close. */
export function ModalDialog({ open, labelledBy, busy = false, onClose, children }: ModalDialogProps) {
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
      aria-labelledby={labelledBy}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
      className="m-auto w-full max-w-[min(30rem,calc(100%-2rem))] rounded-md border border-border bg-surface-raised p-8 text-fg shadow-xl backdrop:bg-fg/40"
    >
      {/* Mounted only while open so each opening starts clean, with no stale form state. */}
      {open && children}
    </dialog>
  )
}
