import type { ComponentProps, ReactNode } from 'react'
import { type ButtonVariant, linkButtonClass } from './buttonStyles'

/** A section of a record or form: a clear heading, then the content. Spacing separates sections, not rules. */
export function FormSection({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <fieldset className="min-w-0 border-0 p-0 pt-2">
      <legend className="sr-only">{title}</legend>
      <h2 className="text-xl font-semibold text-fg">{title}</h2>
      {description && <p className="mt-1 text-sm text-fg-muted">{description}</p>}
      <div className="mt-5 grid gap-6">{children}</div>
    </fieldset>
  )
}

interface PageHeaderProps {
  title: string
  /** Short secondary text next to the title, e.g. a record count. */
  meta?: ReactNode
  /** Plain-text line under the title. */
  description?: string
  /** Primary actions, aligned right. */
  actions?: ReactNode
}

export function PageHeader({ title, meta, description, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight text-fg">{title}</h1>
          {meta && <div className="num text-sm text-fg-muted">{meta}</div>}
        </div>
        {description && <p className="mt-2 text-base text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  ...props
}: ComponentProps<'button'> & { variant?: ButtonVariant; size?: 'md' | 'sm' }) {
  return (
    <button
      type="button"
      {...props}
      className={`${linkButtonClass(variant, size)} disabled:cursor-not-allowed ${className ?? ''}`}
    />
  )
}

export function Alert({ children, tone = 'error' }: { children: ReactNode; tone?: 'error' | 'success' }) {
  const styles = tone === 'error' ? 'border-danger-border bg-danger-soft text-danger-fg' : 'border-success-border bg-success-soft text-success-fg'
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex items-start gap-3 rounded-md border px-4 py-3 text-sm ${styles}`}>
      <span aria-hidden="true" className="mt-[7px] h-2 w-2 shrink-0 rounded-full bg-current" />
      <div className="min-w-0">{children}</div>
    </div>
  )
}
