import { type ReactNode, useState } from 'react'
import { Link, useParams } from 'react-router'
import { JobMatches } from '@/features/candidate-admin'
import { WORK_MODE_LABELS } from '@/features/candidate-profile'
import { ApiError } from '@/shared/api/client'
import { formatPayRange } from '@/shared/format'
import { Alert, Button, PageHeader, Stamp } from '@/shared/ui'
import { EMPLOYMENT_TYPE_LABELS } from '../schema'
import { formatLocation, formatYearRange } from '../format'
import { useJob, useUpdateJob } from '../hooks'
import { detailToFormValues } from '../mapping'
import { CONFLICT_MESSAGE, isVersionConflict } from '../serverErrors'
import type { JobDetail } from '../types'
import { CloseJobDialog } from './CloseJobDialog'
import { EmbeddingStatusStamp } from './EmbeddingStatusStamp'
import { JobForm } from './JobForm'
import { JobStatusStamp } from './JobStatusStamp'

const dateTimeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

const backLink = (
  <Link to="/jobs" className="w-fit rounded-xs text-sm text-accent-fg underline-offset-4 hover:underline">
    ← Back to jobs
  </Link>
)

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="mt-1 text-fg">{children}</dd>
    </div>
  )
}

/** Everything matching depends on; status and owner are left out on purpose. */
const matchKey = (job: JobDetail) =>
  JSON.stringify([
    job.title,
    job.department,
    job.employment_type,
    job.work_mode,
    job.city,
    job.country_code,
    job.min_years,
    job.max_years,
    job.must_have_skills,
    job.nice_to_have_skills,
    job.description,
    job.salary_min,
    job.salary_max,
    job.salary_currency,
  ])

function JobView({ job }: { job: JobDetail }) {
  return (
    <div className="grid gap-8">
      <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Location">{formatLocation(job)}</Fact>
        <Fact label="Work mode">{WORK_MODE_LABELS[job.work_mode]}</Fact>
        <Fact label="Employment type">{EMPLOYMENT_TYPE_LABELS[job.employment_type]}</Fact>
        <Fact label="Experience (years)">
          <span className="num">{formatYearRange(job.min_years, job.max_years)}</span>
        </Fact>
        <Fact label="Yearly pay">
          <span className="num">
            {formatPayRange(job.salary_min, job.salary_max, job.salary_currency) ?? 'Not stated'}
          </span>
        </Fact>
        <Fact label="Owner">{job.created_by.full_name}</Fact>
        <Fact label="Last updated">
          <span className="num">{dateTimeFormat.format(new Date(job.updated_at))}</span>
        </Fact>
      </dl>
      <section aria-labelledby="must-have-heading">
        <h2 id="must-have-heading" className="text-xl font-semibold text-fg">
          Must-have skills
        </h2>
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {job.must_have_skills.map((skill) => (
            <li key={skill}>
              <Stamp tone="brass">{skill}</Stamp>
            </li>
          ))}
        </ul>
      </section>
      {job.nice_to_have_skills.length > 0 && (
        <section aria-labelledby="nice-to-have-heading">
          <h2 id="nice-to-have-heading" className="text-xl font-semibold text-fg">
            Nice-to-have skills
          </h2>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {job.nice_to_have_skills.map((skill) => (
              <li key={skill}>
                <Stamp>{skill}</Stamp>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section aria-labelledby="description-heading">
        <h2 id="description-heading" className="text-xl font-semibold text-fg">
          Description
        </h2>
        <p className="mt-3 max-w-prose whitespace-pre-wrap text-fg">{job.description}</p>
      </section>
    </div>
  )
}

export function JobDetailPage() {
  const { id = '' } = useParams()
  const job = useJob(id)
  const update = useUpdateJob(id)
  const [editing, setEditing] = useState(false)
  const [confirmingClose, setConfirmingClose] = useState(false)
  const [conflict, setConflict] = useState(false)

  if (job.isPending) {
    return (
      <p role="status" className="text-sm text-fg-muted">
        Loading job…
      </p>
    )
  }
  if (job.isError) {
    const notFound = job.error instanceof ApiError && [404, 422].includes(job.error.status)
    return (
      <div className="grid gap-4">
        {backLink}
        <Alert>{notFound ? 'This job does not exist.' : job.error.message}</Alert>
      </div>
    )
  }

  const current = job.data
  const reload = () => {
    setConflict(false)
    setEditing(false)
    void job.refetch()
  }
  const closeJob = () =>
    update.mutate(
      { version: current.version, status: 'closed' },
      {
        onSuccess: () => setConfirmingClose(false),
        onError: (error) => {
          if (isVersionConflict(error)) {
            setConfirmingClose(false)
            setConflict(true)
          }
        },
      },
    )
  const closeError =
    update.error && !isVersionConflict(update.error) ? update.error.message || 'Could not close the job. Please try again.' : null

  return (
    <div className="grid max-w-4xl grid-cols-[minmax(0,1fr)] gap-8">
      {backLink}
      <PageHeader
        title={current.title}
        description={current.department ?? undefined}
        meta={`JOB ${current.id.slice(0, 8)}`}
        actions={
          current.can_edit &&
          !editing && (
            <>
              <Button variant="secondary" onClick={() => setEditing(true)}>
                Edit
              </Button>
              {current.status !== 'closed' && (
                <Button variant="danger" onClick={() => setConfirmingClose(true)}>
                  Close job
                </Button>
              )}
            </>
          )
        }
      />
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <span className="flex items-center gap-2">
          <span className="text-sm text-fg-muted">Status</span>
          <JobStatusStamp status={current.status} />
        </span>
        <span className="flex items-center gap-2">
          <span className="text-sm text-fg-muted">Embedding</span>
          <EmbeddingStatusStamp status={current.embedding_status} />
        </span>
      </div>
      {!current.can_edit && <p className="text-sm text-fg-muted">Only the creator or an admin can edit this job.</p>}
      {conflict && (
        <Alert>
          {CONFLICT_MESSAGE}
          <button type="button" className="ml-2 font-medium underline" onClick={reload}>
            Reload
          </button>
        </Alert>
      )}

      {editing ? (
        <JobForm
          key={current.version}
          defaultValues={detailToFormValues(current)}
          submitLabel="Save changes"
          onCancel={() => setEditing(false)}
          onReloadLatest={reload}
          onSubmit={async (payload) => {
            await update.mutateAsync({ ...payload, version: current.version })
            setEditing(false)
          }}
        />
      ) : (
        <>
          <JobView job={current} />
          {/* Remounted when what's matched changes, so an edit never starts a paid ranking
              without a click; closing or reopening keeps the results. */}
          <JobMatches
            key={matchKey(current)}
            jobId={current.id}
            jobContentKey={matchKey(current)}
            ready={current.embedding_status === 'ready'}
          />
        </>
      )}

      <CloseJobDialog
        open={confirmingClose}
        jobTitle={current.title}
        pending={update.isPending}
        error={closeError}
        onConfirm={closeJob}
        onClose={() => {
          setConfirmingClose(false)
          update.reset()
        }}
      />
    </div>
  )
}
