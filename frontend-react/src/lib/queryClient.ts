import { QueryClient } from '@tanstack/react-query'

/**
 * Build a QueryClient.
 *
 * Exported as a factory (not just a singleton) so each test can get an isolated
 * cache: the app singleton is module state, and a test that shares it inherits
 * whatever the previous test left behind. `createTestQueryClient` in
 * `src/test/queries.ts` is the instance tests should use.
 */
export function createQueryClient(overrides?: Partial<QueryClient['getDefaultOptions']>) {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1000 * 10, // 10 seconds
        gcTime: 1000 * 60 * 5, // 5 minutes
        retry: 1,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
      ...overrides,
    },
  })
}

/** The app-wide client. Production code uses this; tests do not. */
export const queryClient = createQueryClient()
