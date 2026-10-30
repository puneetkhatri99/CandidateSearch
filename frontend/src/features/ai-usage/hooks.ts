import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { getEvents, getSummary, updateBudget } from './api'
import { type EventFilters, FILTER_KEYS } from './types'

const AI_USAGE_KEY = ['ai-usage'] as const

/** Filters live in the URL so a filtered log survives refresh and can be shared as a link. */
export function useEventFilters() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(
    () => Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ''])) as unknown as EventFilters,
    [params],
  )
  const setFilter = useCallback(
    (key: keyof EventFilters, value: string) =>
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

export function useBudgetSummary() {
  return useQuery({
    queryKey: [...AI_USAGE_KEY, 'summary'],
    queryFn: ({ signal }) => getSummary(signal),
    retry: false,
  })
}

export function useUsageEvents(filters: EventFilters) {
  return useInfiniteQuery({
    queryKey: [...AI_USAGE_KEY, 'events', filters],
    queryFn: ({ pageParam, signal }) => getEvents(filters, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

export function useUpdateBudget() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateBudget,
    retry: false,
    onSuccess: (summary) => {
      queryClient.setQueryData([...AI_USAGE_KEY, 'summary'], summary)
    },
  })
}