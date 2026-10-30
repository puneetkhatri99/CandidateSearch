import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useRef } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Alert, Button, TextInput } from '@/shared/ui'

const MAX_LIMIT_USD = 10_000

const limitSchema = z.object({
  limit_usd: z
    .string()
    .trim()
    .regex(/^\d{1,5}(\.\d{1,2})?$/, 'Enter an amount with up to two decimals, like 10.00.')
    .refine((value) => Number(value) <= MAX_LIMIT_USD, `The limit cannot be more than $${MAX_LIMIT_USD.toLocaleString('en-US')}.`),
})
type LimitForm = z.infer<typeof limitSchema>

interface EditLimitDialogProps {
  open: boolean
  currentLimit: string
  pending: boolean
  error: string | null
  onSave: (limitUsd: string) => void
  onClose: () => void
}

function LimitForm({ currentLimit, pending, error, onSave, onClose }: Omit<EditLimitDialogProps, 'open'>) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LimitForm>({ resolver: zodResolver(limitSchema), defaultValues: { limit_usd: Number(currentLimit).toFixed(2) } })

  return (
    <form onSubmit={handleSubmit((values) => onSave(Number(values.limit_usd).toFixed(2)))} noValidate>
      <h2 id="edit-limit-title" className="text-xl font-semibold text-fg">
        Edit spending limit
      </h2>
      <p className="mt-2 text-sm text-fg-muted">
        The limit covers all AI spending, ever. Requests that would go over it are not sent.
      </p>
      <div className="mt-4">
        <TextInput
          label="Limit (USD)"
          inputMode="decimal"
          autoComplete="off"
          className="num"
          autoFocus
          error={errors.limit_usd?.message}
          {...register('limit_usd')}
        />
      </div>
      {error && (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" onClick={onClose} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : 'Save limit'}
        </Button>
      </div>
    </form>
  )
}

/** Native <dialog>: showModal() traps focus, Escape cancels, focus returns to the opener on close. */
export function EditLimitDialog({ open, ...formProps }: EditLimitDialogProps) {
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
      aria-labelledby="edit-limit-title"
      onCancel={(e) => {
        e.preventDefault()
        if (!formProps.pending) formProps.onClose()
      }}
      className="m-auto w-full max-w-[min(28rem,calc(100%-2rem))] rounded-md border border-border bg-surface-raised p-8 text-fg shadow-xl backdrop:bg-black/50"
    >
      {/* Mounted only while open so each opening starts from the current limit with no stale errors. */}
      {open && <LimitForm {...formProps} />}
    </dialog>
  )
}