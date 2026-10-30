import { type ReactNode, useId } from 'react'

export interface FieldA11y {
  id: string
  'aria-invalid': boolean
  'aria-describedby'?: string
}

interface FormFieldProps {
  label: string
  error?: string
  hint?: string
  required?: boolean
  id?: string
  children: (a11y: FieldA11y) => ReactNode
}

/** Error text with a small square marker so the state never relies on colour alone. */
export function FieldError({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <p id={id} className="flex items-start gap-2 text-sm text-danger-fg">
      <span aria-hidden="true" className="mt-[7px] h-2 w-2 shrink-0 rounded-full bg-current" />
      <span>{children}</span>
    </p>
  )
}

/** Label + hint + error wiring shared by every input, so a11y attributes are never forgotten. */
export function FormField({ label, error, hint, required, id, children }: FormFieldProps) {
  const generatedId = useId()
  const fieldId = id ?? generatedId
  const hintId = hint ? `${fieldId}-hint` : undefined
  const errorId = error ? `${fieldId}-error` : undefined
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={fieldId} className="caps text-fg">
        {label}
        {required && (
          <span className="text-danger-fg" aria-hidden="true">
            {' '}
            *
          </span>
        )}
      </label>
      {children({ id: fieldId, 'aria-invalid': Boolean(error), 'aria-describedby': describedBy })}
      {hint && (
        <p id={hintId} className="text-xs text-fg-subtle">
          {hint}
        </p>
      )}
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  )
}

export const inputClass =
  'w-full rounded-sm border border-border-input bg-surface px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-fg ' +
  'placeholder:text-fg-subtle focus:border-focus focus:outline-2 focus:outline-offset-0 focus:outline-focus ' +
  'disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-fg-subtle aria-[invalid=true]:border-danger-fg'
