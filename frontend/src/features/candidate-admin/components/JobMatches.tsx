import { useState } from 'react'
import { Alert, Button } from '@/shared/ui'
import { useJobMatches } from '../hooks'
import { MatchResults } from './MatchResults'
import { SearchProgress } from './SearchProgress'

interface JobMatchesProps {
  jobId: string
  /** Changes when anything matching depends on changes; old results aren't reused then. */
  jobContentKey: string
  /** The job's embedding matches its current text; matching needs it. */
  ready: boolean
}

/** "Find candidates" for a job: an AI ranking (about $0.02) that runs only when asked. */
export function JobMatches({ jobId, jobContentKey, ready }: JobMatchesProps) {
  const [requested, setRequested] = useState(false)
  const matches = useJobMatches(jobId, jobContentKey, { enabled: requested && ready })

  return (
    <section aria-labelledby="matches-heading" className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="matches-heading" className="text-xl font-semibold text-fg">
          Matching candidates
        </h2>
        <Button
          disabled={!ready || matches.isFetching}
          onClick={() => (requested ? void matches.refetch() : setRequested(true))}
        >
          {matches.isFetching ? 'Finding…' : requested ? 'Find again' : 'Find candidates'}
        </Button>
      </div>
      <p className="text-sm text-fg-muted">
        {ready
          ? 'Ranked by AI against this job: skills and location first, then skill strength, pay and experience. Perfect matches meet the job’s minimum years, must-have skills and location.'
          : 'Available once this job’s embedding is ready.'}
      </p>
      {requested && matches.isFetching && <SearchProgress stages={matches.stages} label="Matching progress" />}
      {!requested || matches.isPending ? null : matches.isError ? (
        <Alert>{matches.error.message || 'Matching failed. Please try again.'}</Alert>
      ) : matches.data.items.length + matches.data.filtered_out.length === 0 ? (
        <p className="text-fg-muted">No candidates found for this job yet.</p>
      ) : (
        <>
          {matches.data.ranked_by === 'search' && (
            <p className="text-sm text-fg-muted">AI ranking unavailable, so these are in search order.</p>
          )}
          <MatchResults result={matches.data} filtered fetching={matches.isFetching} />
        </>
      )}
    </section>
  )
}
