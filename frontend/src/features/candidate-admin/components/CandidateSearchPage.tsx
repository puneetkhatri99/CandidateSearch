import { useState } from 'react'
import { Link } from 'react-router'
import { useCurrentUser } from '@/features/auth'
import { Alert, Button, inputClass, linkButtonClass, PageHeader } from '@/shared/ui'
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue'
import { MIN_QUERY_LENGTH, useCandidateSearch, useDeleteCandidate, useMeaningSearch, useSearchFilters } from '../hooks'
import { type CandidateSummary, FILTER_NAMES } from '../types'
import { CandidateFilters } from './CandidateFilters'
import { CandidateTable, CandidateTableSkeleton } from './CandidateTable'
import { DeleteCandidateDialog } from './DeleteCandidateDialog'
import { MatchResults } from './MatchResults'
import { SearchProgress } from './SearchProgress'

// Typed filters change the URL on every keystroke; requests wait for a pause.
const FILTER_DEBOUNCE_MS = 300

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`

export function CandidateSearchPage() {
  const { filters, setFilter, clearFilters } = useSearchFilters()
  const [query, setQuery] = useState(filters.q)
  const requested = useDebouncedValue(filters, FILTER_DEBOUNCE_MS)
  // A search is paid, so it uses the filters as they were when Search was pressed (or the page
  // opened); editing a filter afterwards waits for the next press.
  const [submitted, setSubmitted] = useState(filters)

  // With search text: hybrid search, ranked by AI, then split by the filters (a paid call, so
  // only on submit). Without: the newest candidates that pass the filters.
  const searching = filters.q.length >= MIN_QUERY_LENGTH
  const searched = { ...submitted, q: filters.q }
  const filtersOn = FILTER_NAMES.some((name) => (searching ? searched : requested)[name].trim() !== '')
  const filtersPending = searching && FILTER_NAMES.some((name) => filters[name] !== submitted[name])
  const browse = useCandidateSearch(requested, { enabled: !searching })
  const search = useMeaningSearch(searched, { enabled: searching })
  const active = searching ? search : browse

  const perfectCount = search.data?.items.length ?? 0
  const browsed = browse.data?.pages.flatMap((page) => page.items) ?? []
  const total = searching ? perfectCount + (search.data?.filtered_out.length ?? 0) : browsed.length

  const { data: user } = useCurrentUser()
  const deletion = useDeleteCandidate()
  const [deleting, setDeleting] = useState<CandidateSummary | null>(null)
  const onDelete = user?.role === 'admin' ? setDeleting : undefined
  const closeDeleteDialog = () => {
    setDeleting(null)
    deletion.reset()
  }
  const clearAll = () => {
    setQuery('')
    clearFilters()
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Candidates"
        meta={
          total > 0 && (
            <p aria-live="polite">
              {!searching
                ? `Showing ${plural(total, 'candidate')}${browse.hasNextPage ? ' (more available)' : ''}`
                : filtersOn
                  ? `${perfectCount} of the top ${plural(total, 'candidate')} match every filter`
                  : `Top ${plural(total, 'candidate')}, best match first`}
            </p>
          )
        }
        actions={
          <Link to="/admin/candidates/new" className={linkButtonClass('primary')}>
            Add candidate
          </Link>
        }
      />

      <div role="search" className="grid gap-6">
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            setSubmitted(filters)
            setFilter('q', query.trim())
          }}
        >
          <label className="caps flex flex-1 flex-col gap-1.5 text-fg">
            Search
            <input
              type="search"
              className={inputClass}
              placeholder="Describe who you need, e.g. “fastapi developer in ghaziabad, 5 years”"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                // Emptying the box goes back to browsing, which costs nothing.
                if (!e.target.value.trim()) setFilter('q', '')
              }}
            />
          </label>
          <Button type="submit">Search</Button>
        </form>
        <CandidateFilters filters={filters} onChange={setFilter} onClear={clearAll} />
        {filtersPending && <p className="text-sm text-fg-muted">Press Search to apply the changed filters.</p>}
        {searching && search.data && (
          <p className="text-sm text-fg-muted">
            {search.data.ranked_by === 'search'
              ? 'AI ranking unavailable, so these are in search order. '
              : 'Ranked by AI: skills and location first, then experience. '}
            Filters are applied after ranking.
          </p>
        )}
      </div>

      {searching && search.isFetching && <SearchProgress stages={search.stages} />}
      {active.isError ? (
        <Alert>{active.error.message || 'Search failed. Please try again.'}</Alert>
      ) : active.isPending ? (
        // A search shows its live steps above instead of a skeleton.
        !searching && <CandidateTableSkeleton />
      ) : total === 0 ? (
        <div className="rounded-md bg-surface-muted px-6 py-12 text-center">
          <p className="text-fg-muted">No candidates match your search.</p>
          <Button variant="secondary" className="mt-4" onClick={clearAll}>
            Clear search and filters
          </Button>
        </div>
      ) : searching && search.data ? (
        <MatchResults result={search.data} filtered={filtersOn} fetching={search.isFetching} onDelete={onDelete} />
      ) : (
        <>
          <div className={browse.isFetching && !browse.isFetchingNextPage ? 'opacity-60 transition-opacity' : undefined}>
            <CandidateTable candidates={browsed} onDelete={onDelete} />
          </div>
          {browse.hasNextPage && (
            <div>
              <Button
                variant="secondary"
                onClick={() => void browse.fetchNextPage()}
                disabled={browse.isFetchingNextPage}
              >
                {browse.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      )}

      <DeleteCandidateDialog
        open={deleting !== null}
        candidateName={deleting?.full_name ?? ''}
        pending={deletion.isPending}
        error={deletion.error ? deletion.error.message || 'Could not delete. Please try again.' : null}
        onClose={closeDeleteDialog}
        onConfirm={() => {
          if (deleting) deletion.mutate(deleting.id, { onSuccess: closeDeleteDialog })
        }}
      />
    </div>
  )
}
