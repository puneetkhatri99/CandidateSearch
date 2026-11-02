import { useBookmarks, useToggleBookmark } from '../hooks'
import type { CandidateSummary } from '../types'

/** A star that adds the person to, or removes them from, the team's shared bookmarks. */
export function BookmarkButton({ candidate }: { candidate: CandidateSummary }) {
  const bookmarks = useBookmarks()
  const toggle = useToggleBookmark()
  const bookmark = bookmarks.data?.items.find((b) => b.candidate.id === candidate.id)
  const bookmarked = bookmark !== undefined

  return (
    <button
      type="button"
      aria-pressed={bookmarked}
      aria-label={`Bookmark ${candidate.full_name}`}
      title={bookmarked ? `Bookmarked by ${bookmark.added_by_name}` : 'Bookmark for the team'}
      disabled={bookmarks.isPending || toggle.isPending}
      onClick={() => toggle.mutate({ candidate, bookmarked: !bookmarked })}
      className={`rounded-xs text-lg leading-none disabled:opacity-50 ${bookmarked ? 'text-accent-fg' : 'text-fg-muted hover:text-fg'}`}
    >
      <span aria-hidden="true">{bookmarked ? '★' : '☆'}</span>
    </button>
  )
}
