import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import type { ProfilePayload } from '@/features/candidate-profile'
import {
  createCandidate,
  deleteCandidate,
  getCandidate,
  matchCandidatesToJob,
  searchByMeaning,
  searchCandidates,
  updateCandidate,
} from './api'
import { type CandidateDetail, FILTER_KEYS, type SearchFilters, type StageEvent } from './types'

/** Shorter queries carry too little meaning to embed (the API rejects them too). */
export const MIN_QUERY_LENGTH = 2

const keys = {
  search: (filters: SearchFilters) => ['candidates', 'search', filters] as const,
  meaning: (filters: SearchFilters) => ['candidates', 'search', 'meaning', filters] as const,
  // Not under the search prefix: invalidating searches must not start a paid ranking by itself.
  jobMatches: (jobId: string, jobContentKey: string) => ['job-matches', jobId, jobContentKey] as const,
  allSearches: ['candidates', 'search'] as const,
  detail: (id: string) => ['candidates', 'detail', id] as const,
}

/** Filters live in the URL so a search survives refresh and can be shared as a link. */
export function useSearchFilters() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(
    () => Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ''])) as unknown as SearchFilters,
    [params],
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
  const clearFilters = useCallback(() => setParams(new URLSearchParams(), { replace: true }), [setParams])
  return { filters, setFilter, clearFilters }
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

/** The streamed steps of the run in progress; each new run starts an empty log. */
function useStageLog() {
  const [stages, setStages] = useState<StageEvent[]>([])
  const begin = useCallback(() => {
    setStages([])
    return (event: StageEvent) => setStages((seen) => [...seen, event])
  }, [])
  return { stages, begin }
}

export function useMeaningSearch(filters: SearchFilters, { enabled = true } = {}) {
  const { stages, begin } = useStageLog()
  const query = useQuery({
    queryKey: keys.meaning(filters),
    queryFn: ({ signal }) => searchByMeaning(filters, signal, begin()),
    placeholderData: keepPreviousData,
    retry: false,
    // Each new query is a paid OpenAI call; don't refetch on focus or remount.
    staleTime: 5 * 60_000,
    enabled,
  })
  return { ...query, stages }
}

/** Runs only once `enabled` (the "Find candidates" button), since each run is a paid AI call. */
export function useJobMatches(jobId: string, jobContentKey: string, { enabled = true } = {}) {
  const { stages, begin } = useStageLog()
  const query = useQuery({
    queryKey: keys.jobMatches(jobId, jobContentKey),
    queryFn: ({ signal }) => matchCandidatesToJob(jobId, signal, begin()),
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

export function useDeleteCandidate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: deleteCandidate,
    retry: false,
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: keys.detail(id) })
      void queryClient.invalidateQueries({ queryKey: keys.allSearches })
    },
  })
}
