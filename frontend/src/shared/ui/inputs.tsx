import { type ComponentProps, type ReactNode, useId } from 'react'
import { FieldError, FormField, inputClass } from './FormField'

interface FieldProps {
  label: string
  error?: string
  hint?: string
}

export function TextInput({ label, error, hint, required, className, ...props }: FieldProps & ComponentProps<'input'>) {
  return (
    <FormField label={label} error={error} hint={hint} required={required} id={props.id}>
      {(a11y) => <input {...props} {...a11y} required={required} className={`${inputClass} ${className ?? ''}`} />}
    </FormField>
  )
}

export function TextArea({ label, error, hint, required, className, ...props }: FieldProps & ComponentProps<'textarea'>) {
  return (
    <FormField label={label} error={error} hint={hint} required={required} id={props.id}>
      {(a11y) => (
        <textarea {...props} {...a11y} required={required} className={`${inputClass} min-h-28 leading-relaxed ${className ?? ''}`} />
      )}
    </FormField>
  )
}

export function SelectInput({
  label,
  error,
  hint,
  required,
  children,
  className,
  ...props
}: FieldProps & ComponentProps<'select'> & { children: ReactNode }) {
  return (
    <FormField label={label} error={error} hint={hint} required={required} id={props.id}>
      {(a11y) => (
        <select {...props} {...a11y} required={required} className={`${inputClass} ${className ?? ''}`}>
          {children}
        </select>
      )}
    </FormField>
  )
}

export function Checkbox({ label, error, ...props }: { label: ReactNode; error?: string } & ComponentProps<'input'>) {
  const errorId = useId()
  return (
    <div className="flex flex-col gap-1.5">
      <label className="inline-flex items-start gap-2.5 text-sm text-fg">
        <input
          type="checkbox"
          {...props}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-accent"
        />
        <span>{label}</span>
      </label>
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  )
}
