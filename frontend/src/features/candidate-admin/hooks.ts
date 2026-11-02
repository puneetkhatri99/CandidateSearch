import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import type { ProfilePayload } from '@/features/candidate-profile'
import {
  attachResume,
  createCandidate,
  deleteCandidate,
  deleteSavedSearch,
  getCandidate,
  getSavedSearch,
  listBookmarks,
  listSavedSearches,
  matchCandidatesToJob,
  searchByMeaning,
  searchCandidates,
  setBookmark,
  starSavedSearch,
  updateCandidate,
} from './api'
import {
  type BookmarkList,
  type CandidateDetail,
  type CandidateSummary,
  FILTER_KEYS,
  FILTER_NAMES,
  type SavedSearchDetail,
  type SearchFilters,
  type SemanticSearchResult,
  type StageEvent,
} from './types'

/** Shorter queries carry too little meaning to embed (the API rejects them too). */
export const MIN_QUERY_LENGTH = 2

// AI results (search by meaning, job matches) sit outside the 'candidates' prefix: invalidating
// candidate lists must never start a paid ranking by itself.
const AI_RESULTS = [['candidate-meaning-search'], ['job-matches']] as const

const keys = {
  search: (filters: SearchFilters) => ['candidates', 'search', filters] as const,
  meaning: (filters: SearchFilters) => [...AI_RESULTS[0], filters] as const,
  jobMatches: (jobId: string, jobContentKey: string) => [...AI_RESULTS[1], jobId, jobContentKey] as const,
  allSearches: ['candidates', 'search'] as const,
  detail: (id: string) => ['candidates', 'detail', id] as const,
  bookmarks: ['candidates', 'bookmarks'] as const,
  // Free to refetch (no AI call), so candidate edits and deletes may invalidate them.
  savedSearches: ['saved-searches'] as const,
  savedSearch: (id: string) => ['saved-searches', 'detail', id] as const,
  history: ['saved-searches', 'list'] as const,
}

/** Filters live in the URL so a search survives refresh and can be shared as a link. `search`
 * is the saved copy of the search shown, so reopening it is free. */
export function useSearchFilters() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(
    () => Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ''])) as unknown as SearchFilters,
    [params],
  )
  const savedId = params.get('search')
  const setSavedId = useCallback(
    (id: string | null) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (id) next.set('search', id)
          else next.delete('search')
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  const setFilter = useCallback(
    (key: keyof SearchFilters, value: string) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (value) next.set(key, value)
          else next.delete(key)
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  // One update, because two functional updates in the same tick can overwrite each other.
  const startSearch = useCallback(
    (q: string) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          next.delete('search') // a new search replaces the one shown
          if (q) next.set('q', q)
          else next.delete('q')
          return next
        },
        { replace: true },
      ),
    [setParams],
  )
  const clearFilters = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams])
  return { filters, setFilter, clearFilters, savedId, setSavedId, startSearch }
}

/** A saved search reopened; it never changes, and reopening it makes no AI call. */
export function useSavedSearch(id: string | null) {
  return useQuery({
    queryKey: keys.savedSearch(id ?? ''),
    queryFn: ({ signal }) => getSavedSearch(id ?? '', signal),
    enabled: id !== null,
    retry: false,
    staleTime: Infinity,
  })
}

/** Puts a finished search in the saved-search cache, so pointing the URL at it costs nothing. */
export function useRememberSavedSearch() {
  const queryClient = useQueryClient()
  return useCallback(
    (filters: SearchFilters, result: SemanticSearchResult) => {
      if (!result.saved_search_id) return
      const detail: SavedSearchDetail = {
        query: filters.q,
        filters: Object.fromEntries(FILTER_NAMES.filter((name) => filters[name]).map((name) => [name, filters[name]])),
        starred: false,
        created_at: new Date().toISOString(),
        result,
      }
      queryClient.setQueryData(keys.savedSearch(result.saved_search_id), detail)
      void queryClient.invalidateQueries({ queryKey: keys.history })
    },
    [queryClient],
  )
}

export function useSearchHistory() {
  return useInfiniteQuery({
    queryKey: keys.history,
    queryFn: ({ pageParam, signal }) => listSavedSearches(pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  })
}

export function useStarSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, starred }: { id: string; starred: boolean }) => starSavedSearch(id, starred),
    retry: false,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.savedSearches }),
  })
}

export function useDeleteSavedSearch() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteSavedSearch,
    retry: false,
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: keys.savedSearch(id) })
      void queryClient.invalidateQueries({ queryKey: keys.history })
    },
  })
}

export function useCandidateSearch(filters: SearchFilters, { enabled = true } = {}) {
  return useInfiniteQuery({
    queryKey: keys.search(filters),
    queryFn: ({ pageParam, signal }) => searchCandidates(filters, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    retry: false,
    enabled,
  })
}

/** The streamed steps of the run in progress; each new run starts empty. */
function useRunLog() {
  const [stages, setStages] = useState<StageEvent[]>([])
  const begin = useCallback(() => {
    setStages([])
    return { onStage: (event: StageEvent) => setStages((seen) => [...seen, event]) }
  }, [])
  return { stages, begin }
}

export function useMeaningSearch(filters: SearchFilters, { enabled = true } = {}) {
  const { stages, begin } = useRunLog()
  const query = useQuery({
    queryKey: keys.meaning(filters),
    // No abort signal: the server finishes (and pays for) a search even when the page drops it,
    // so cancelling on unmount (React StrictMode, navigating back) only paid for it twice.
    queryFn: () => searchByMeaning(filters, begin()),
    retry: false,
    // Each new query is a paid OpenAI call; don't refetch on focus or remount.
    staleTime: 5 * 60_000,
    enabled,
  })
  return { ...query, stages }
}

/** Runs only once `enabled` (the "Find candidates" button), since each run is a paid AI call. */
export function useJobMatches(jobId: string, jobContentKey: string, { enabled = true } = {}) {
  const { stages, begin } = useRunLog()
  const query = useQuery({
    queryKey: keys.jobMatches(jobId, jobContentKey),
    queryFn: () => matchCandidatesToJob(jobId, begin()), // no abort signal, as above
    retry: false,
    staleTime: 5 * 60_000,
    enabled,
  })
  return { ...query, stages }
}

export function useCandidate(id: string) {
  return useQuery({
    queryKey: keys.detail(id),
    queryFn: ({ signal }) => getCandidate(id, signal),
    retry: false,
  })
}

export function useCreateStaffCandidate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createCandidate,
    retry: false,
    onSuccess: (created) => {
      queryClient.setQueryData(keys.detail(created.id), created)
      void queryClient.invalidateQueries({ queryKey: keys.allSearches })
    },
  })
}

export function useUpdateCandidate(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProfilePayload & { version: number }) => updateCandidate(id, payload),
    retry: false,
    onSuccess: (updated: CandidateDetail) => {
      queryClient.setQueryData(keys.detail(id), updated)
      void queryClient.invalidateQueries({ queryKey: keys.allSearches })
    },
  })
}

export function useAttachResume(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => attachResume(id, file),
    retry: false,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.detail(id) }),
  })
}

/** The team's shared bookmarks, newest first; every star on the page reads from this one list. */
export function useBookmarks() {
  return useQuery({ queryKey: keys.bookmarks, queryFn: ({ signal }) => listBookmarks(signal) })
}

export function useToggleBookmark() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ candidate, bookmarked }: { candidate: CandidateSummary; bookmarked: boolean }) =>
      setBookmark(candidate.id, bookmarked),
    retry: false,
    // Optimistic: the star flips at once and flips back if the call fails.
    onMutate: async ({ candidate, bookmarked }) => {
      await queryClient.cancelQueries({ queryKey: keys.bookmarks })
      const previous = queryClient.getQueryData<BookmarkList>(keys.bookmarks)
      if (previous) {
        const others = previous.items.filter((b) => b.candidate.id !== candidate.id)
        const added = { candidate, added_by_name: 'You', added_at: new Date().toISOString() }
        queryClient.setQueryData<BookmarkList>(keys.bookmarks, { items: bookmarked ? [added, ...others] : others })
      }
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(keys.bookmarks, context.previous)
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.bookmarks }),
  })
}

export function useDeleteCandidate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteCandidate,
    retry: false,
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: keys.detail(id) })
      void queryClient.invalidateQueries({ queryKey: keys.allSearches })
      void queryClient.invalidateQueries({ queryKey: keys.bookmarks })
      // Drop the person from AI results in place: re-running would pay for a new ranking.
      const without = (result: SemanticSearchResult | undefined) =>
        result && {
          ...result,
          items: result.items.filter((match) => match.candidate.id !== id),
          filtered_out: result.filtered_out.filter((match) => match.candidate.id !== id),
        }
      for (const queryKey of AI_RESULTS) queryClient.setQueriesData({ queryKey }, without)
      // Saved searches are free to reload; the server dropped the person from them.
      void queryClient.invalidateQueries({ queryKey: keys.savedSearches })
    },
  })
}
