import { Link } from 'react-router'
import { WORK_MODE_LABELS } from '@/features/candidate-profile'
import { Alert, Button, linkButtonClass, PageHeader, SelectInput, Stamp } from '@/shared/ui'
import { formatLocation, formatYearRange } from '../format'
import { useJobs, useStatusFilter } from '../hooks'
import { EMPLOYMENT_TYPE_LABELS, JOB_STATUS_LABELS, JOB_STATUSES } from '../schema'
import type { StatusFilter } from '../types'
import { JobStatusStamp } from './JobStatusStamp'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const COLUMNS = ['Title', 'Department', 'Location', 'Work mode', 'Type', 'Years', 'Must-have skills', 'Status', 'Owner', 'Updated']
const VISIBLE_SKILLS = 5
const cell = 'px-3 py-4 align-top'

export function JobListPage() {
  const [status, setStatus] = useStatusFilter()
  const jobs = useJobs(status)
  const items = jobs.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Jobs"
        meta={items.length > 0 && <p aria-live="polite">Showing {items.length} job{items.length === 1 ? '' : 's'}{jobs.hasNextPage ? ' (more available)' : ''}</p>}
        actions={
          <Link to="/jobs/new" className={linkButtonClass('primary')}>
            Add job
          </Link>
        }
      />

      <div className="max-w-xs">
        <SelectInput label="Status" value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}>
          <option value="">All statuses</option>
          {JOB_STATUSES.map((value) => (
            <option key={value} value={value}>
              {JOB_STATUS_LABELS[value]}
            </option>
          ))}
        </SelectInput>
      </div>

      {jobs.isError ? (
        <Alert>{jobs.error.message || 'Could not load the jobs. Please try again.'}</Alert>
      ) : jobs.isPending ? (
        <p role="status" className="text-sm text-fg-muted">
          Loading jobs…
        </p>
      ) : items.length === 0 ? (
        <div className="rounded-md bg-surface-muted px-6 py-12 text-center">
          <p className="text-fg-muted">{status ? `No ${JOB_STATUS_LABELS[status].toLowerCase()} jobs.` : 'No jobs yet.'}</p>
          <Link to="/jobs/new" className={`${linkButtonClass('primary')} mt-4`}>
            Add job
          </Link>
        </div>
      ) : (
        <>
          <div className={`overflow-x-auto ${jobs.isFetching && !jobs.isFetchingNextPage ? 'opacity-60 transition-opacity' : ''}`}>
            <table className="min-w-full text-left">
              <caption className="sr-only">Job roles</caption>
              <thead className="border-b border-border text-fg-muted">
                <tr>
                  {COLUMNS.map((column) => (
                    <th key={column} scope="col" className={`whitespace-nowrap px-3 py-3 text-sm font-medium ${column === 'Years' ? 'text-right' : ''}`}>
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {items.map((job) => (
                  <tr key={job.id} className="transition-colors hover:bg-surface-muted">
                    <td className={cell}>
                      <Link to={`/jobs/${job.id}`} className="rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline">
                        {job.title}
                      </Link>
                    </td>
                    <td className={`${cell} text-fg-muted`}>{job.department ?? '—'}</td>
                    <td className={`${cell} whitespace-nowrap text-fg-muted`}>{formatLocation(job)}</td>
                    <td className={cell}>
                      <Stamp>{WORK_MODE_LABELS[job.work_mode]}</Stamp>
                    </td>
                    <td className={`${cell} whitespace-nowrap text-fg-muted`}>{EMPLOYMENT_TYPE_LABELS[job.employment_type]}</td>
                    <td className={`${cell} num whitespace-nowrap text-right text-data text-fg`}>{formatYearRange(job.min_years, job.max_years)}</td>
                    <td className={cell}>
                      <div className="flex flex-wrap gap-1">
                        {job.must_have_skills.slice(0, VISIBLE_SKILLS).map((skill) => (
                          <Stamp key={skill}>{skill}</Stamp>
                        ))}
                        {job.must_have_skills.length > VISIBLE_SKILLS && (
                          <Stamp>+{job.must_have_skills.length - VISIBLE_SKILLS}</Stamp>
                        )}
                      </div>
                    </td>
                    <td className={cell}>
                      <JobStatusStamp status={job.status} />
                    </td>
                    <td className={`${cell} text-fg-muted`}>{job.created_by.full_name}</td>
                    <td className={`${cell} num whitespace-nowrap text-data text-fg-muted`}>{dateFormat.format(new Date(job.updated_at))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {jobs.hasNextPage && (
            <div>
              <Button variant="secondary" onClick={() => void jobs.fetchNextPage()} disabled={jobs.isFetchingNextPage}>
                {jobs.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
