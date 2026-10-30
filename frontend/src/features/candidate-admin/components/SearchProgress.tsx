import { STAGES, type Stage, type StageEvent } from '../types'

const LABELS: Record<Stage, string> = {
  embedding: 'Embedding',
  retrieval: 'Retrieval',
  augmentation: 'Augmentation',
  ranking: 'AI ranking',
  filtering: 'Filtering',
}
// Shown until the server reports the step, so the pipeline reads ahead of time.
const WAITING: Record<Stage, string> = {
  embedding: 'Turn the request into a vector',
  retrieval: 'Find the closest profiles by meaning and keywords',
  augmentation: 'Prepare an anonymised brief',
  ranking: 'Judge each candidate',
  filtering: 'Split by the hard filters',
}

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
      <span
        aria-hidden="true"
        className="flex size-5 items-center justify-center rounded-full border border-success-border bg-success-soft text-xs text-success-fg"
      >
        ✓
      </span>
    )
  }
  if (status === 'active') {
    return (
      <span
        aria-hidden="true"
        className="size-5 rounded-full border-2 border-accent border-t-transparent motion-safe:animate-spin"
      />
    )
  }
  return <span aria-hidden="true" className="size-5 rounded-full border-2 border-border" />
}

/** Live steps of a streamed search: embedding → retrieval → augmentation → ranking → filtering. */
export function SearchProgress({ stages, label = 'Search progress' }: { stages: StageEvent[]; label?: string }) {
  const statuses = STAGES.map((stage, index) => statusOf(stage, stages, index))
  const current = STAGES.find((_, index) => statuses[index] === 'active')

  return (
    <div className="rounded-md border border-border bg-surface-muted px-4 py-4">
      <p role="status" aria-live="polite" className="sr-only">
        {current ? `${LABELS[current]} in progress` : 'Preparing results'}
      </p>
      <ol aria-label={label} className="grid gap-3 sm:grid-cols-5 sm:gap-4">
        {STAGES.map((stage, index) => {
          const status = statuses[index] ?? 'waiting'
          const done = [...stages].reverse().find((event) => event.stage === stage && event.state === 'done')
          const started = stages.find((event) => event.stage === stage && event.state === 'started')
          return (
            <li key={stage} className="flex items-start gap-3 sm:flex-col sm:gap-2" data-status={status}>
              <Marker status={status} />
              <div className="grid min-w-0 gap-0.5">
                <span className={`text-sm font-medium ${status === 'waiting' ? 'text-fg-muted' : 'text-fg'}`}>
                  {LABELS[stage]}
                  <span className="sr-only">: {status === 'done' ? 'done' : status === 'active' ? 'in progress' : 'waiting'}</span>
                </span>
                <span className="text-xs text-fg-muted">{done?.detail ?? started?.detail ?? WAITING[stage]}</span>
                {done?.elapsed_ms != null && <span className="num text-xs text-fg-subtle">{done.elapsed_ms} ms</span>}
              </div>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
