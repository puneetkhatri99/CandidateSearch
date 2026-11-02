import { Link } from 'react-router'
import { Alert, Button, PageHeader } from '@/shared/ui'
import { useDeleteSavedSearch, useSearchHistory, useStarSearch } from '../hooks'
import { FILTER_LABELS, type FilterName, type SavedSearchSummary } from '../types'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

/** Reopens the search on the Candidates page from its saved copy: free, no AI call. */
function openUrl(search: SavedSearchSummary) {
  const params = new URLSearchParams({ q: search.query })
  for (const [name, value] of Object.entries(search.filters)) params.set(name, String(value))
  params.set('search', search.id)
  return `/admin/candidates?${params}`
}

function filterWords(search: SavedSearchSummary) {
  return Object.entries(search.filters)
    .map(([name, value]) => `${FILTER_LABELS[name as FilterName]}: ${value}`)
    .join(' · ')
}

function SavedSearchRow({ search }: { search: SavedSearchSummary }) {
  const star = useStarSearch()
  const removal = useDeleteSavedSearch()
  const filters = filterWords(search)

  return (
    <li className="grid gap-1 py-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link to={openUrl(search)} className="rounded-xs font-semibold text-accent-fg underline-offset-4 hover:underline">
          {search.query}
        </Link>
        <div className="ml-auto flex gap-2">
          <Button
            variant="secondary"
            aria-pressed={search.starred}
            aria-label={`${search.starred ? 'Unstar' : 'Star'} “${search.query}”`}
            disabled={star.isPending}
            onClick={() => star.mutate({ id: search.id, starred: !search.starred })}
          >
            <span aria-hidden="true">{search.starred ? '★ Starred' : '☆ Star'}</span>
          </Button>
          <Button
            variant="secondary"
            aria-label={`Delete “${search.query}”`}
            disabled={removal.isPending}
            onClick={() => removal.mutate(search.id)}
          >
            Delete
          </Button>
        </div>
      </div>
      {filters && <p className="text-sm text-fg-muted">{filters}</p>}
      <p className="num text-sm text-fg-muted">
        {search.result_count} {search.result_count === 1 ? 'match' : 'matches'}
        {search.filtered_out_count > 0 && `, ${search.filtered_out_count} filtered out`} ·{' '}
        {dateFormat.format(new Date(search.created_at))}
      </p>
      {(star.isError || removal.isError) && <p className="text-sm text-danger-fg">That didn’t work. Please try again.</p>}
    </li>
  )
}

function SavedSearchList({ title, searches }: { title: string; searches: SavedSearchSummary[] }) {
  if (searches.length === 0) return null
  return (
    <section className="grid gap-2" aria-label={title}>
      <h2 className="font-semibold text-fg">{title}</h2>
      <ul className="divide-y divide-border border-y border-border">
        {searches.map((search) => (
          <SavedSearchRow key={search.id} search={search} />
        ))}
      </ul>
    </section>
  )
}

/** Your own past searches with their results; only you see them. */
export function SavedSearchesPage() {
  const history = useSearchHistory()
  const searches = history.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="grid max-w-3xl grid-cols-[minmax(0,1fr)] gap-8">
      <PageHeader
        title="Saved searches"
        description="Your 50 most recent searches are kept with their results; starred ones stay until you delete them. Opening one costs nothing. Only you see these."
      />
      {history.isPending ? (
        <p role="status" className="text-sm text-fg-muted">
          Loading saved searches…
        </p>
      ) : history.isError ? (
        <Alert>{history.error.message || 'Could not load saved searches. Please try again.'}</Alert>
      ) : searches.length === 0 ? (
        <p className="text-fg-muted">No searches yet. Search on the Candidates page and it will appear here.</p>
      ) : (
        <>
          <SavedSearchList title="Starred" searches={searches.filter((s) => s.starred)} />
          <SavedSearchList title="Recent" searches={searches.filter((s) => !s.starred)} />
          {history.hasNextPage && (
            <div>
              <Button variant="secondary" onClick={() => void history.fetchNextPage()} disabled={history.isFetchingNextPage}>
                {history.isFetchingNextPage ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
