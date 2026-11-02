import { type ChangeEvent, useRef, useState } from 'react'
import { MAX_RESUME_BYTES, ReadingResume, RESUME_FILE_TYPES } from '@/features/candidate-profile'
import { Alert, Button, linkButtonClass } from '@/shared/ui'
import { formattedResumeUrl } from '../api'
import { useAttachResume } from '../hooks'
import type { CandidateDetail } from '../types'

/** See the formatted resume, or upload one (replacing any earlier) without touching the profile. */
export function ResumeBar({ candidate }: { candidate: CandidateDetail }) {
  const input = useRef<HTMLInputElement>(null)
  const attach = useAttachResume(candidate.id)
  const [fileError, setFileError] = useState<string | null>(null)
  const [fileName, setFileName] = useState<string | null>(null)

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    setFileError(null)
    attach.reset()
    if (!file) return
    setFileName(file.name)
    if (file.size > MAX_RESUME_BYTES) {
      setFileError('The file is too large. Upload one under 4 MB.')
      return
    }
    attach.mutate(file)
  }

  const error = fileError ?? (attach.error ? attach.error.message || 'Could not read the resume. Please try again.' : null)

  return (
    <section aria-label="Resume" className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3">
        {candidate.has_resume ? (
          <a href={formattedResumeUrl(candidate.id)} target="_blank" rel="noopener noreferrer" className={linkButtonClass('primary')}>
            See resume
          </a>
        ) : (
          <p className="text-sm text-fg-muted">No resume uploaded yet.</p>
        )}
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={attach.isPending}>
          {attach.isPending ? 'Reading resume…' : candidate.has_resume ? 'Replace resume' : 'Upload resume'}
        </Button>
        <input ref={input} type="file" accept={RESUME_FILE_TYPES} onChange={onFile} className="sr-only" tabIndex={-1} aria-label="Resume file" />
      </div>
      {attach.isPending && <ReadingResume fileName={fileName} note="The profile fields won't change." />}
      {attach.isSuccess && <Alert tone="success">Resume uploaded and read. Open the formatted version with See resume.</Alert>}
      {error && <Alert>{error}</Alert>}
    </section>
  )
}
