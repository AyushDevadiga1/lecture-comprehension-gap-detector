import { QueryClient } from '@tanstack/react-query'

/**
 * An isolated QueryClient for one test.
 *
 * Two things differ from the app's client, both for determinism:
 *   - `retry: false`, so a failed request surfaces as one rejection instead of
 *     a silent retry loop. The app retries once; a test that means to assert on
 *     an error must not have to wait for the retry, and a test that means to
 *     assert on success will not see a flake from a double fetch.
 *   - `gcTime: 0`, so a test's cache is collectable as soon as it finishes
 *     rather than lingering for five minutes of wall clock.
 */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
}
