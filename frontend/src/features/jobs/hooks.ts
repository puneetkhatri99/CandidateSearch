import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { createJob, getJob, listJobs, updateJob } from './api'
import type { JobPayload } from './schema'
import type { JobDetail, StatusFilter } from './types'

const keys = {
  list: (status: StatusFilter) => ['jobs', 'list', status] as const,
  allLists: ['jobs', 'list'] as const,
  detail: (id: string) => ['jobs', 'detail', id] as const,
}

const STATUS_VALUES: readonly StatusFilter[] = ['', 'draft', 'open', 'closed']

/** The status filter lives in the URL so a filtered list survives refresh and can be shared. */
export function useStatusFilter(): [StatusFilter, (status: StatusFilter) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get('status') ?? ''
  const status = STATUS_VALUES.find((value) => value === raw) ?? ''
  const setStatus = useCallback(
    (next: StatusFilter) =>
      setParams(
        (prev) => {
          const updated = new URLSearchParams(prev)
          if (next) updated.set('status', next)
          else updated.delete('status')
          return updated
        },
        { replace: true },
      ),
    [setParams],
  )
  return [status, setStatus]
}

export function useJobs(status: StatusFilter) {
  return useInfiniteQuery({
    queryKey: keys.list(status),
    queryFn: ({ pageParam, signal }) => listJobs(status, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

// A new job is embedded within seconds; the page polls so "Find candidates" unlocks by itself.
// It gives up after about 2 minutes: with no API key or the background runner off, the job
// stays "pending" for good and the page would otherwise poll for as long as it's open.
const EMBEDDING_POLL_MS = 3000
const EMBEDDING_MAX_POLLS = 40

export function useJob(id: string) {
  return useQuery({
    queryKey: keys.detail(id),
    queryFn: ({ signal }) => getJob(id, signal),
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.embedding_status === 'pending' && query.state.dataUpdateCount < EMBEDDING_MAX_POLLS
        ? EMBEDDING_POLL_MS
        : false,
  })
}

export function useCreateJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createJob,
    retry: false,
    onSuccess: (created) => {
      queryClient.setQueryData(keys.detail(created.id), created)
      void queryClient.invalidateQueries({ queryKey: keys.allLists })
    },
  })
}

export function useUpdateJob(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: Partial<JobPayload> & { version: number }) => updateJob(id, payload),
    retry: false,
    onSuccess: (updated: JobDetail) => {
      queryClient.setQueryData(keys.detail(id), updated)
      void queryClient.invalidateQueries({ queryKey: keys.allLists })
    },
  })
}
