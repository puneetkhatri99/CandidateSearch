import { type KeyboardEvent, useState } from 'react'
import { FormField, inputClass } from './FormField'

interface TagInputProps {
  label: string
  value: string[]
  onChange: (value: string[]) => void
  onBlur?: () => void
  normalize?: (tag: string) => string
  maxItems?: number
  error?: string
  hint?: string
  required?: boolean
  placeholder?: string
  name?: string
}

/** Free-text tags: Enter or comma adds, Backspace on an empty input removes the last one. */
export function TagInput({
  label,
  value,
  onChange,
  onBlur,
  normalize = (t) => t.trim(),
  maxItems,
  error,
  hint,
  required,
  placeholder,
  name,
}: TagInputProps) {
  const [draft, setDraft] = useState('')
  const isFull = maxItems !== undefined && value.length >= maxItems

  const commit = (raw: string) => {
    const tags = raw.split(',').map(normalize).filter(Boolean)
    const next = [...value]
    for (const tag of tags) {
      if (!next.includes(tag) && (maxItems === undefined || next.length < maxItems)) next.push(tag)
    }
    if (next.length !== value.length) onChange(next)
    setDraft('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      commit(draft)
    } else if (event.key === 'Backspace' && draft === '' && value.length > 0) {
      onChange(value.slice(0, -1))
    }
  }

  return (
    <FormField label={label} error={error} hint={hint} required={required}>
      {(a11y) => (
        <div className="flex flex-col gap-2">
          {value.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label={`${label} added`}>
              {value.map((tag) => (
                <li
                  key={tag}
                  className="inline-flex items-center gap-1 rounded-full bg-accent-soft py-0.5 pl-3 pr-1 text-sm text-accent-soft-fg"
                >
                  {tag}
                  <button
                    type="button"
                    onClick={() => onChange(value.filter((t) => t !== tag))}
                    className="rounded-full px-1.5 text-accent-fg hover:bg-accent-soft-hover hover:text-fg"
                    aria-label={`Remove ${tag}`}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <input
            {...a11y}
            name={name}
            className={inputClass}
            value={draft}
            disabled={isFull}
            placeholder={isFull ? `Maximum of ${maxItems} reached` : placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            onBlur={() => {
              if (draft.trim()) commit(draft)
              onBlur?.()
            }}
          />
        </div>
      )}
    </FormField>
  )
}
