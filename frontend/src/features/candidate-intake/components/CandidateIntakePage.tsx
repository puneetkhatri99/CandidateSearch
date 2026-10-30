import { useState } from 'react'
import type { CandidateCreated } from '../types'
import { CandidateForm } from './CandidateForm'

export function CandidateIntakePage() {
  const [submitted, setSubmitted] = useState<CandidateCreated | null>(null)

  if (submitted) {
    return (
      <section role="status" className="rounded-md border border-success-border bg-success-soft p-8">
        <h1 className="text-3xl font-semibold tracking-tight text-success-fg">Thanks, your profile was received</h1>
        <p className="mt-3 max-w-prose text-base text-fg-muted">
          We'll match it against open roles and a recruiter will reach out if there's a fit.
        </p>
      </section>
    )
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight text-fg">Create your candidate profile</h1>
      <p className="mt-2 text-base text-fg-muted">
        Fields marked <span className="text-danger-fg">*</span> are required. It takes about 5 minutes.
      </p>
      <div className="mt-10">
        <CandidateForm
          onSubmitted={(result) => {
            setSubmitted(result)
            window.scrollTo({ top: 0 })
          }}
        />
      </div>
    </div>
  )
}
