import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { handleAuthApiError } from '@/features/auth'

/** One place for query defaults and the global error hook (a pending password change). */
export function createQueryClient(): QueryClient {
  const queryClient: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => handleAuthApiError(queryClient, error) }),
    mutationCache: new MutationCache({ onError: (error) => handleAuthApiError(queryClient, error) }),
    defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
  })
  return queryClient
}
