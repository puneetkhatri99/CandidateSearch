import { Meter, useElapsedSeconds } from '@/shared/ui'
import { STAGES, type Stage, type StageEvent } from '../types'

const LABELS: Record<Stage, string> = {
  embedding: 'Understanding the request',
  retrieval: 'Finding likely people',
  augmentation: 'Hiding personal details',
  ranking: 'Judging each person',
  filtering: 'Checking filters',
}
// Shown until the server reports the step, so the pipeline reads ahead of time.
const WAITING: Record<Stage, string> = {
  embedding: 'Works out what you need',
  retrieval: 'Looks by meaning and by keywords',
  augmentation: 'The AI never sees names or contact details',
  ranking: 'Weighs skills, location, pay and experience',
  filtering: 'Separates who meets every requirement',
}
// Measured on real searches of about 1,000 profiles (docs/LEARNINGS.md, 2026-11-02).
const USUAL_WAIT = 'Usually takes 20 to 30 seconds'

type Status = 'waiting' | 'active' | 'done'

function statusOf(stage: Stage, events: StageEvent[], index: number): Status {
  const seen = events.filter((event) => event.stage === stage)
  if (seen.some((event) => event.state === 'done')) return 'done'
  if (seen.length > 0) return 'active'
  // Before the first event arrives the request itself is under way: show step one as active.
  return index === 0 && events.length === 0 ? 'active' : 'waiting'
}

function Marker({ status }: { status: Status }) {
  if (status === 'done') {
    return (
      <span aria-hidden="true" className="flex size-4 shrink-0 items-center justify-center text-xs text-success-fg">
        ✓
      </span>
    )
  }
  if (status === 'active') {
    return (
      <span
        aria-hidden="true"
        className="size-4 shrink-0 rounded-full border-2 border-accent border-t-transparent motion-safe:animate-spin"
      />
    )
  }
  return <span aria-hidden="true" className="size-4 shrink-0 rounded-full border-2 border-border" />
}

/** Live steps of a streamed search, in a recruiter's words. The quick steps sit on one line; the
 * step under way is the big thing, with a real count once the AI is judging people. */
export function SearchProgress({ stages, label = 'Search progress' }: { stages: StageEvent[]; label?: string }) {
  const seconds = useElapsedSeconds()
  const statuses = STAGES.map((stage, index) => statusOf(stage, stages, index))
  const current = STAGES.find((_, index) => statuses[index] === 'active')
  const latest = current ? [...stages].reverse().find((event) => event.stage === current) : undefined
  const count = latest?.state === 'progress' && latest.completed != null && latest.total ? latest : undefined
  // What the finished steps found, in their own words ("Looking first in Delhi", "Found 100 profiles").
  const findings = STAGES.flatMap((stage) => {
    const done = [...stages].reverse().find((event) => event.stage === stage && event.state === 'done')
    return done?.detail ? [done.detail] : []
  })

  return (
    <div className="grid gap-4 rounded-md border border-border bg-surface-muted px-4 py-4">
      <p role="status" aria-live="polite" className="sr-only">
        {current ? `${LABELS[current]} in progress` : 'Preparing results'}
      </p>
      <ol aria-label={label} className="flex flex-wrap gap-x-5 gap-y-2">
        {STAGES.map((stage, index) => {
          const status = statuses[index] ?? 'waiting'
          return (
            <li key={stage} className="flex items-center gap-2" data-status={status}>
              <Marker status={status} />
              <span className={`text-sm ${status === 'waiting' ? 'text-fg-muted' : 'text-fg'} ${status === 'active' ? 'font-medium' : ''}`}>
                {LABELS[stage]}
                <span className="sr-only">: {status === 'done' ? 'done' : status === 'active' ? 'in progress' : 'waiting'}</span>
              </span>
            </li>
          )
        })}
      </ol>

      {current && (
        <div className="grid gap-2">
          <p className="text-lg font-semibold text-fg">{count?.detail ?? LABELS[current]}</p>
          {count ? (
            <Meter percent={((count.completed ?? 0) / (count.total ?? 1)) * 100} tone="ok" label="Profiles judged" />
          ) : (
            <p className="text-sm text-fg-muted">{latest?.detail ?? WAITING[current]}</p>
          )}
        </div>
      )}

      {findings.length > 0 && <p className="text-sm text-fg-muted">{findings.join(' · ')}</p>}
      <p className="num text-xs text-fg-muted">
        {USUAL_WAIT} · {seconds} s so far
      </p>
    </div>
  )
}
