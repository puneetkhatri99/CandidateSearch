import { useState } from 'react'
import type { UseFormRegisterReturn } from 'react-hook-form'
import { Button, TextInput } from '@/shared/ui'

interface TemporaryPasswordFieldProps {
  inputProps: UseFormRegisterReturn
  error?: string
  hint: string
  onGenerate: () => void
  getValue: () => string
}

/** The password is shown in the open on purpose: the admin has to pass it on to its owner. */
export function TemporaryPasswordField({ inputProps, error, hint, onGenerate, getValue }: TemporaryPasswordFieldProps) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(getValue())
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="grid gap-2">
      <TextInput
        label="Temporary password"
        type="text"
        autoComplete="off"
        spellCheck={false}
        required
        className="num"
        hint={hint}
        error={error}
        {...inputProps}
        onChange={(event) => {
          setCopied(false)
          return inputProps.onChange(event)
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setCopied(false)
            onGenerate()
          }}
        >
          Generate
        </Button>
        <Button variant="secondary" size="sm" onClick={() => void copy()}>
          Copy
        </Button>
        <span role="status" className="text-sm text-fg-muted">
          {copied ? 'Copied' : ''}
        </span>
      </div>
    </div>
  )
}
