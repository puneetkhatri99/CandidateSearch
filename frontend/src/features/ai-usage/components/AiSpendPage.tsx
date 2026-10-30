import { useState } from 'react'
import { useCurrentUser } from '@/features/auth'
import { Alert, Button, PageHeader, SelectInput } from '@/shared/ui'
import { useBudgetSummary, useEventFilters, useUpdateBudget, useUsageEvents } from '../hooks'
import { EVENT_STATUSES } from '../types'
import { BudgetCard } from './BudgetCard'
import { EditLimitDialog } from './EditLimitDialog'
import { EventLog, EventLogSkeleton } from './EventLog'
import { TotalsTable } from './TotalsTable'

function BudgetSkeleton() {
  return (
    <div role="status" className="max-w-3xl rounded-md border border-border bg-surface-raised p-8">
      <span className="sr-only">Loading budget…</span>
      <div aria-hidden="true" className="grid gap-3">
        <div className="h-10 w-1/3 rounded-sm bg-surface-muted" />
        <div className="h-5 rounded-sm bg-surface-muted" />
      </div>
    </div>
  )
}

/** Keeps a selected value selectable even if the summary no longer lists it. */
const withCurrent = (keys: string[], current: string) => (current && !keys.includes(current) ? [...keys, current] : keys)

export function AiSpendPage() {
  const { data: user } = useCurrentUser()
  const summary = useBudgetSummary()
  const { filters, setFilter, clearFilters } = useEventFilters()
  const events = useUsageEvents(filters)
  const budgetUpdate = useUpdateBudget()
  const [editing, setEditing] = useState(false)

  const closeEditor = () => {
    setEditing(false)
    budgetUpdate.reset()
  }
  const items = events.data?.pages.flatMap((page) => page.items) ?? []
  const hasFilters = Boolean(filters.model || filters.operation || filters.status)

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-10">
      <PageHeader title="AI spending" />

      {summary.isError ? (
        <Alert>{summary.error.message || 'Could not load the budget. Please try again.'}</Alert>
      ) : summary.isPending ? (
        <BudgetSkeleton />
      ) : (
        <>
          <BudgetCard summary={summary.data} onEdit={user?.role === 'admin' ? () => setEditing(true) : undefined} />
          <div className="grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-2">
            <TotalsTable caption="Spending by model" keyLabel="Model" rows={summary.data.by_model} />
            <TotalsTable caption="Spending by operation" keyLabel="Operation" rows={summary.data.by_operation} />
          </div>
          <EditLimitDialog
            open={editing}
            currentLimit={summary.data.limit_usd}
            pending={budgetUpdate.isPending}
            error={budgetUpdate.error ? budgetUpdate.error.message || 'Could not save the limit. Please try again.' : null}
            onClose={closeEditor}
            onSave={(limit) => budgetUpdate.mutate(limit, { onSuccess: closeEditor })}
          />
        </>
      )}

      <section aria-labelledby="log-heading" className="grid grid-cols-[minmax(0,1fr)] gap-4">
        <h2 id="log-heading" className="text-xl font-semibold text-fg">
          Request log
        </h2>
        <div role="search" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SelectInput label="Model" value={filters.model} onChange={(e) => setFilter('model', e.target.value)}>
            <option value="">Any model</option>
            {withCurrent(summary.data?.by_model.map((row) => row.key) ?? [], filters.model).map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </SelectInput>
          <SelectInput label="Operation" value={filters.operation} onChange={(e) => setFilter('operation', e.target.value)}>
            <option value="">Any operation</option>
            {withCurrent(summary.data?.by_operation.map((row) => row.key) ?? [], filters.operation).map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </SelectInput>
          <SelectInput label="Status" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
            <option value="">Any status</option>
            {EVENT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </SelectInput>
          <div className="flex items-end">
            <Button variant="secondary" onClick={clearFilters}>
              Clear filters
            </Button>
          </div>
        </div>

        {events.isError ? (
          <Alert>{events.error.message || 'Could not load requests. Please try again.'}</Alert>
        ) : events.isPending ? (
          <EventLogSkeleton />
        ) : items.length === 0 ? (
          <div className="rounded-md bg-surface-muted px-6 py-12 text-center">
            <p className="text-fg-muted">{hasFilters ? 'No requests match these filters.' : 'No AI requests yet.'}</p>
          </div>
        ) : (
          <>
            <div className={events.isFetching && !events.isFetchingNextPage ? 'opacity-60 transition-opacity' : undefined}>
              <EventLog events={items} />
            </div>
            {events.hasNextPage && (
              <div>
                <Button variant="secondary" onClick={() => void events.fetchNextPage()} disabled={events.isFetchingNextPage}>
                  {events.isFetchingNextPage ? 'Loading…' : 'Load more'}
                </Button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}