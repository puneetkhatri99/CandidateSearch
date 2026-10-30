export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'dangerSolid'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary: 'border border-transparent bg-accent text-on-accent hover:bg-accent-hover disabled:bg-accent-disabled',
  secondary:
    'border border-border-input bg-transparent text-fg hover:bg-surface-muted disabled:text-fg-subtle disabled:hover:bg-transparent',
  danger: 'border border-danger-border bg-transparent text-danger-fg hover:bg-danger-soft disabled:text-danger-fg/50',
  dangerSolid: 'border border-transparent bg-danger text-on-danger hover:bg-danger-hover disabled:opacity-60',
}

/** Style a link like a button (the Button component itself renders a <button>). */
export const linkButtonClass = (variant: ButtonVariant = 'primary', size: 'md' | 'sm' = 'md') =>
  `inline-flex items-center justify-center rounded-sm font-medium transition-colors ${
    size === 'sm' ? 'px-3 py-1.5 text-sm' : 'px-4 py-2.5 text-sm'
  } ${BUTTON_VARIANTS[variant]}`
