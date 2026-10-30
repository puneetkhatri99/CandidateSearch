import { Button, Meter, Stamp, type StampTone } from '@/shared/ui'
import { budgetTone, type BudgetTone, formatUsd, WARNING_PERCENT } from '../format'
import type { BudgetSummary } from '../types'

const FIGURE_COLORS: Record<BudgetTone, string> = {
  ok: 'text-fg',
  warning: 'text-warning-fg',
  danger: 'text-danger-fg',
}

const STATE_STAMPS: Record<BudgetTone, { tone: StampTone; text: string }> = {
  ok: { tone: 'success', text: 'Within limit' },
  warning: { tone: 'warning', text: 'Near limit' },
  danger: { tone: 'dangerSolid', text: 'Limit reached' },
}

interface BudgetCardProps {
  summary: BudgetSummary
  /** Provided only for admins; recruiters see the budget without the Edit action. */
  onEdit?: () => void
}

export function BudgetCard({ summary, onEdit }: BudgetCardProps) {
  const tone = budgetTone(summary.percent_used, summary.limit_reached)
  const state = STATE_STAMPS[tone]

  return (
    <section aria-labelledby="budget-heading" className="max-w-3xl rounded-md border border-border bg-surface-raised p-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="budget-heading" className="text-xl font-semibold text-fg">
            Lifetime budget
          </h2>
          <Stamp tone={state.tone}>{state.text}</Stamp>
        </div>
        {onEdit && (
          <Button variant="secondary" size="sm" onClick={onEdit}>
            Edit limit
          </Button>
        )}
      </div>

      <p className={`num mt-6 text-4xl font-semibold tracking-tight ${FIGURE_COLORS[tone]}`}>{formatUsd(summary.spent_usd)}</p>
      <p className="num mt-2 text-data text-fg-muted">of {formatUsd(summary.limit_usd)} lifetime limit</p>

      <div className="mt-6">
        <Meter percent={summary.percent_used} tone={tone} label="Budget used" markerPercent={WARNING_PERCENT} />
      </div>

      {summary.limit_reached && (
        <p className="mt-2 text-sm font-medium text-danger-fg">
          Spending has reached the limit, so AI requests are paused. Raise the limit to resume.
        </p>
      )}

      <dl className="mt-8 grid gap-6 sm:grid-cols-2">
        <div>
          <dt className="caps text-fg-muted">Remaining</dt>
          <dd className="num mt-1 text-lg font-medium text-fg">{formatUsd(summary.remaining_usd)}</dd>
        </div>
        <div>
          <dt className="caps text-fg-muted">Used</dt>
          <dd className="num mt-1 text-lg font-medium text-fg">{summary.percent_used.toFixed(1)}%</dd>
        </div>
      </dl>
    </section>
  )
}
