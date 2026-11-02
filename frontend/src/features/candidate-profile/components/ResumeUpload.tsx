import { useMutation } from '@tanstack/react-query'
import { type ChangeEvent, type DragEvent, useRef, useState } from 'react'
import { type FieldValues, type Path, type PathValue, useFormContext } from 'react-hook-form'
import { Alert, Button, FormSection, useElapsedSeconds } from '@/shared/ui'
import { fillFromResume, MAX_RESUME_BYTES, readResume, RESUME_FILE_TYPES } from '../resume'
import type { ProfileFormValues } from '../schema'

const TOO_LARGE = 'The file is too large. Upload one under 10 MB.'
// ResumeAI's guide: 5-30 s normally; a scanned PDF or a service waking from idle takes longer.
const USUAL_SECONDS = 30

function FileIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="size-8">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" strokeLinejoin="round" />
      <path d="M14 3v5h5M12 17v-6m0 0-2.5 2.5M12 11l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Shown while ResumeAI reads a file: what is happening, and an honest clock. */
export function ReadingResume({ fileName, note }: { fileName: string | null; note?: string }) {
  const seconds = useElapsedSeconds()
  return (
    <div role="status" className="grid gap-3 rounded-md border border-accent-border bg-accent-soft px-4 py-4">
      <div className="flex items-center gap-3">
        <span aria-hidden="true" className="size-5 shrink-0 rounded-full border-2 border-accent border-t-transparent motion-safe:animate-spin" />
        <p className="min-w-0 text-base font-semibold text-fg">
          Reading <span className="break-all">{fileName ?? 'the resume'}</span>
        </p>
      </div>
      <p className="text-sm text-fg-muted">
        The AI is picking out the name, contact details, skills, jobs and education.{note ? ` ${note}` : ''}
      </p>
      <p className="num text-xs text-fg-muted">
        {seconds < USUAL_SECONDS
          ? `Usually 5 to 30 seconds · ${seconds} s so far`
          : `Taking longer than usual (${seconds} s). A scanned PDF can take up to 2 minutes; please keep this page open.`}
      </p>
    </div>
  )
}

interface ResumeUploadProps {
  /** Who is uploading, for the wording: the candidate themselves, or staff for them. */
  audience: 'candidate' | 'staff'
}

/**
 * Reads a resume and fills the empty profile fields. The form must have a `resume_ref` field,
 * sent with the new profile so the resume is linked to it.
 */
export function ResumeUpload({ audience }: ResumeUploadProps) {
  const { getValues, setValue } = useFormContext<ProfileFormValues & { resume_ref: string } & FieldValues>()
  const input = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [filled, setFilled] = useState<string[] | null>(null)
  const [dragging, setDragging] = useState(false)
  const read = useMutation({ mutationFn: readResume, retry: false })

  const readFile = (file: File | undefined) => {
    setFileError(null)
    setFilled(null)
    read.reset()
    if (!file) return
    setFileName(file.name)
    if (file.size > MAX_RESUME_BYTES) {
      setFileError(TOO_LARGE)
      return
    }
    read.mutate(file, {
      onSuccess: ({ resume_ref, profile }) => {
        const fill = fillFromResume(getValues(), profile)
        for (const [name, value] of Object.entries(fill.values)) {
          const field = name as Path<ProfileFormValues>
          setValue(field, value as PathValue<ProfileFormValues, typeof field>, { shouldDirty: true })
        }
        setValue('resume_ref', resume_ref)
        setFilled(fill.filled)
      },
    })
  }

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = '' // so choosing the same file again still triggers a read
    readFile(file)
  }

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault()
    setDragging(false)
    if (!read.isPending) readFile(event.dataTransfer.files[0])
  }

  const you = audience === 'candidate' ? 'your' : "the candidate's"
  const error = fileError ?? (read.error ? read.error.message || 'Could not read the resume. Please try again.' : null)

  return (
    <FormSection
      title="Resume"
      description={`Optional. Upload ${you} resume and we'll fill in the form below for you.`}
    >
      <div className="grid gap-3">
        <input
          ref={input}
          type="file"
          accept={RESUME_FILE_TYPES}
          onChange={onFile}
          disabled={read.isPending}
          aria-label={audience === 'candidate' ? 'Your resume' : 'Resume file'}
          className="peer sr-only"
        />

        {read.isPending ? (
          <ReadingResume fileName={fileName} />
        ) : filled ? (
          <div className="grid gap-3 rounded-md border border-success-border bg-success-soft px-4 py-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="flex min-w-0 items-center gap-3 text-base font-semibold text-fg">
                <span aria-hidden="true" className="flex size-6 shrink-0 items-center justify-center rounded-full bg-success text-sm text-on-accent">
                  ✓
                </span>
                <span role="status">
                  {filled.length > 0
                    ? `Filled in ${filled.length} ${filled.length === 1 ? 'field' : 'fields'} from the resume`
                    : 'Resume added'}
                </span>
              </p>
              <Button variant="secondary" size="sm" onClick={() => input.current?.click()}>
                Use a different file
              </Button>
            </div>
            {fileName && <p className="break-all text-sm text-fg-muted">{fileName}</p>}
            {filled.length > 0 ? (
              <>
                <ul aria-label="Filled in from the resume" className="flex flex-wrap gap-2">
                  {filled.map((label) => (
                    <li key={label} className="rounded-full border border-success-border bg-surface px-2.5 py-0.5 text-xs font-medium text-success-fg">
                      {label}
                    </li>
                  ))}
                </ul>
                <p className="text-sm text-fg">
                  <strong className="font-semibold">Next:</strong> check these below (AI can misread a resume), fill in
                  anything missing, then {audience === 'candidate' ? 'submit the profile' : 'press Add candidate'}. The
                  resume is attached when you save.
                </p>
              </>
            ) : (
              <p className="text-sm text-fg">
                Every field it covers was already filled in, so nothing changed. The resume is attached when you save.
              </p>
            )}
          </div>
        ) : (
          <label
            onClick={(event) => {
              // The hidden input is outside the label, so open the picker ourselves.
              event.preventDefault()
              input.current?.click()
            }}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`grid cursor-pointer justify-items-center gap-2 rounded-md border-2 border-dashed px-6 py-8 text-center transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus ${
              dragging ? 'border-accent bg-accent-soft text-accent-soft-fg' : 'border-border-input text-fg-muted hover:border-accent hover:bg-accent-soft'
            }`}
          >
            <FileIcon />
            <span className="text-base text-fg">
              <span className="font-semibold text-accent-fg">Choose a file</span> or drag it here
            </span>
            <span className="text-sm">PDF, Word or text · up to 4 pages · 10 MB</span>
          </label>
        )}

        {error && <Alert>{error}</Alert>}
        <p className="text-sm text-fg-muted">
          The resume is sent to ResumeAI, our resume service, which reads it with AI.{' '}
          {audience === 'candidate' ? 'See the privacy notice below.' : 'The candidate must have agreed to the privacy notice.'}
        </p>
      </div>
    </FormSection>
  )
}
