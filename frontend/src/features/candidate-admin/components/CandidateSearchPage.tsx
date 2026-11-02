import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { useCurrentUser } from '@/features/auth'
import { Alert, Button, inputClass, linkButtonClass, PageHeader } from '@/shared/ui'
import { useDebouncedValue } from '@/shared/hooks/useDebouncedValue'
import {
  MIN_QUERY_LENGTH,
  useCandidateSearch,
  useDeleteCandidate,
  useMeaningSearch,
  useRememberSavedSearch,
  useSavedSearch,
  useSearchFilters,
  useStarSearch,
} from '../hooks'
import { forgetLastSearch, readLastSearch, rememberLastSearch } from '../lastSearch'
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
  const { search } = useLocation()
  // A bare /admin/candidates (the profile's back link, the sidebar, a new tab) reopens the search
  // on screen until Clear or a new search (user decision). Redirecting before the page mounts
  // means its search box starts filled in.
  const last = search ? null : readLastSearch()
  if (last) return <Navigate replace to={{ search: last }} />
  return <CandidateSearch />
}

function CandidateSearch() {
  const { filters, setFilter, clearFilters, savedId, setSavedId, startSearch } = useSearchFilters()
  const location = useLocation()
  const [query, setQuery] = useState(filters.q)
  const requested = useDebouncedValue(filters, FILTER_DEBOUNCE_MS)
  // A search is paid, so it uses the filters as they were when Search was pressed (or the page
  // opened); editing a filter afterwards waits for the next press.
  const [submitted, setSubmitted] = useState(filters)

  // With search text: hybrid search, ranked by AI, then split by the filters (a paid call, so
  // only on submit). Without: the newest candidates that pass the filters.
  const searching = filters.q.length >= MIN_QUERY_LENGTH
  const searched = useMemo(() => ({ ...submitted, q: filters.q }), [submitted, filters.q])
  const filtersOn = FILTER_NAMES.some((name) => (searching ? searched : requested)[name].trim() !== '')
  const filtersPending = searching && FILTER_NAMES.some((name) => filters[name] !== submitted[name])
  const browse = useCandidateSearch(requested, { enabled: !searching })
  // With `search=<id>` in the URL the page shows that saved copy (free); otherwise it runs one.
  const reopened = searching ? savedId : null
  const saved = useSavedSearch(reopened)
  const search = useMeaningSearch(searched, { enabled: searching && reopened === null })
  const remember = useRememberSavedSearch()
  const star = useStarSearch()

  const finished = search.isFetching ? undefined : search.data
  useEffect(() => {
    // A finished search points the URL at its saved copy, so Back or a refresh reopens it free.
    if (!finished?.saved_search_id || reopened !== null) return
    remember(searched, finished)
    setSavedId(finished.saved_search_id)
  }, [finished, reopened, searched, remember, setSavedId])
  useEffect(() => {
    if (reopened !== null) rememberLastSearch(location.search)
  }, [reopened, location.search])

  const starred = saved.data?.starred
  const active = searching ? (reopened !== null ? saved : search) : browse
  // The list appears only once the AI has finished; until then the progress panel shows.
  const results = reopened !== null ? saved.data?.result : search.isFetching ? undefined : search.data

  const perfectCount = results?.items.length ?? 0
  const filteredOutCount = results?.filtered_out.length ?? 0
  const browsed = browse.data?.pages.flatMap((page) => page.items) ?? []
  const total = searching ? perfectCount + filteredOutCount : browsed.length

  const { data: user } = useCurrentUser()
  const deletion = useDeleteCandidate()
  const [deleting, setDeleting] = useState<CandidateSummary | null>(null)
  const onDelete = user?.role === 'admin' ? setDeleting : undefined
  const closeDeleteDialog = () => {
    setDeleting(null)
    deletion.reset()
  }
  const clearAll = () => {
    forgetLastSearch()
    setQuery('')
    clearFilters()
  }
  const noMatches = (
    <div className="rounded-md bg-surface-muted px-6 py-12 text-center">
      <p className="text-fg-muted">No candidates match your search.</p>
      <Button variant="secondary" className="mt-4" onClick={clearAll}>
        Clear search and filters
      </Button>
    </div>
  )

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
      <PageHeader
        title="Candidates"
        meta={
          total > 0 && (
            <p aria-live="polite">
              {!searching
                ? `Showing ${plural(total, 'candidate')}${browse.hasNextPage ? ' (more available)' : ''}`
                : `Checked ${plural(results?.checked ?? 0, 'profile')}, ` +
                  (filtersOn ? `${perfectCount} meet every filter` : `best ${perfectCount} shown`)}
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
            startSearch(query.trim())
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
                // Emptying the box ends the search and goes back to browsing, which costs nothing.
                if (!e.target.value.trim()) {
                  forgetLastSearch()
                  startSearch('')
                }
              }}
            />
          </label>
          <Button type="submit">Search</Button>
        </form>
        <CandidateFilters filters={filters} onChange={setFilter} onClear={clearAll} />
        {filtersPending && <p className="text-sm text-fg-muted">Press Search to apply the changed filters.</p>}
        {searching && results && (
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="text-sm text-fg-muted">
              {results.ranked_by === 'search'
                ? 'AI ranking unavailable, so these are in search order. '
                : 'Ranked by AI: skills first, with location unless the role is remote, then experience. '}
              Filters, and any budget in your search, are applied after ranking.
            </p>
            {reopened !== null && starred !== undefined && (
              <Button
                variant="secondary"
                aria-pressed={starred}
                disabled={star.isPending}
                onClick={() => star.mutate({ id: reopened, starred: !starred })}
              >
                <span aria-hidden="true">{starred ? '★ ' : '☆ '}</span>
                {starred ? 'Starred search' : 'Star this search'}
              </Button>
            )}
          </div>
        )}
      </div>

      {searching && search.isFetching && <SearchProgress stages={search.stages} />}
      {reopened !== null && saved.isError ? (
        <Alert>This saved search is no longer available. Press Search to run it again.</Alert>
      ) : active.isError ? (
        <Alert>{active.error.message || 'Search failed. Please try again.'}</Alert>
      ) : searching ? (
        // A search shows its live steps above instead of a skeleton.
        results && (total === 0 ? (
          noMatches
        ) : (
          <MatchResults result={results} filtered={filtersOn} onDelete={onDelete} />
        ))
      ) : browse.isPending ? (
        <CandidateTableSkeleton />
      ) : total === 0 ? (
        noMatches
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
