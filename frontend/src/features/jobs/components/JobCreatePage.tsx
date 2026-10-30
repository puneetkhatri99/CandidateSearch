import { Link, useNavigate } from 'react-router'
import { PageHeader } from '@/shared/ui'
import { useCreateJob } from '../hooks'
import { emptyJob } from '../schema'
import { JobForm } from './JobForm'

export function JobCreatePage() {
  const navigate = useNavigate()
  const create = useCreateJob()

  return (
    <div className="grid max-w-4xl grid-cols-[minmax(0,1fr)] gap-10">
      <Link to="/jobs" className="w-fit rounded-xs text-sm text-accent-fg underline-offset-4 hover:underline">
        ← Back to jobs
      </Link>
      <PageHeader title="Add job" />
      <JobForm
        defaultValues={emptyJob()}
        submitLabel="Add job"
        onCancel={() => navigate('/jobs')}
        onSubmit={async (payload) => {
          const created = await create.mutateAsync(payload)
          navigate(`/jobs/${created.id}`, { replace: true })
        }}
      />
    </div>
  )
}
