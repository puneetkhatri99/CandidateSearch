import { Link } from 'react-router'
import { formatYears } from '@/shared/format'
import { Alert, PageHeader } from '@/shared/ui'
import { useBookmarks } from '../hooks'
import { BookmarkButton } from './BookmarkButton'

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
const COLUMNS = ['Name', 'Headline', 'Location', 'Years', 'Added by', 'Added', 'Bookmark']
const cell = 'px-3 py-4 align-top'

/** The team's shared list of starred candidates. */
export function BookmarksPage() {
  const bookmarks = useBookmarks()

  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-8">
      <PageHeader title="Bookmarks" description="Candidates the team has starred. Everyone sees the same list." />
      {bookmarks.isPending ? (
        <p role="status" className="text-sm text-fg-muted">
          Loading bookmarks…
        </p>
      ) : bookmarks.isError ? (
        <Alert>{bookmarks.error.message || 'Could not load bookmarks. Please try again.'}</Alert>
      ) : bookmarks.data.items.length === 0 ? (
        <p className="text-fg-muted">No bookmarks yet. Star a candidate to keep them here.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left">
            <caption className="sr-only">Bookmarked candidates</caption>
            <thead className="border-b border-border text-fg-muted">
              <tr>
                {COLUMNS.map((column) => (
                  <th key={column} scope="col" className={`caps whitespace-nowrap px-3 py-3 ${column === 'Years' ? 'text-right' : ''}`}>
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {bookmarks.data.items.map(({ candidate: c, added_by_name, added_at }) => (
                <tr key={c.id} className="transition-colors hover:bg-surface-muted">
                  <td className={cell}>
                    <Link to={`/admin/candidates/${c.id}`} className="rounded-xs font-medium text-accent-fg underline-offset-4 hover:underline">
                      {c.full_name}
                    </Link>
                  </td>
                  <td className={`${cell} min-w-48 text-fg-muted`}>{c.headline}</td>
                  <td className={`${cell} whitespace-nowrap text-fg-muted`}>
                    {c.city}, <span className="num text-data">{c.country_code}</span>
                  </td>
                  <td className={`${cell} num text-right text-data text-fg`}>{formatYears(c.years_experience)}</td>
                  <td className={`${cell} whitespace-nowrap text-fg-muted`}>{added_by_name}</td>
                  <td className={`${cell} num whitespace-nowrap text-data text-fg-muted`}>{dateFormat.format(new Date(added_at))}</td>
                  <td className={cell}>
                    <BookmarkButton candidate={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
