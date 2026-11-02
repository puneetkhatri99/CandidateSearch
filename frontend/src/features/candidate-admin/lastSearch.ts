/**
 * The URL of the search on screen, so the Candidates page reopens it (back link, sidebar,
 * a new tab) until Clear or a new search. Holds only the query string: the search text, filters
 * and a saved-search id, never results. Storage can be unavailable, so every access is guarded.
 */
const KEY = 'candidateSearch.lastSearch'

export function readLastSearch(): string | null {
  try {
    return window.localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function rememberLastSearch(search: string) {
  try {
    window.localStorage.setItem(KEY, search)
  } catch {
    // A private window or blocked storage: the search just won't be reopened later.
  }
}

export function forgetLastSearch() {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // As above.
  }
}
