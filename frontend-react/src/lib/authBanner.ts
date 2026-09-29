import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import type { DefaultOptions } from '@tanstack/react-query'
import { LecGapApiError } from '../api/client'

/**
 * One 401 banner, everywhere. Never a silent "no courses".
 *
 * REACT_ARCHITECTURE.md §6 lists this as a consequence of one request path, and
 * the roadmap's non-negotiables: "401 = one banner, never a dead 'no courses'
 * state". `api/client.ts` had a docstring *promising* it — "401 is extracted
 * here and re-thrown as a typed ApiError so one banner covers it everywhere" —
 * but nothing rendered one, and the Navbar's course query destructured only
 * `data`. So a key-guarded backend produced a course picker reading "No courses
 * found" and two dashboards that looked merely empty. That is the exact failure
 * this module exists to end, and it is the one that misleads a reader into
 * thinking their data is gone.
 *
 * ## Why a cache-level handler
 *
 * React Query is the only place that sees every read, so a `QueryCache.onError`
 * is the single interception point. Doing it in the client would have to push
 * into a store the client does not own; doing it in each component is the
 * duplication §6 forbids.
 *
 * The flag is *sticky* on purpose: a 401 that arrives once should not be cleared
 * by the next successful read, because the read succeeding is exactly the
 * confusing part. It clears when the key is fixed, or on an explicit retry.
 */

export interface AuthBanner {
  /** Null when there is nothing to report. */
  message: string | null
  /** The last 401 seen, for a "retry" affordance. */
  lastSeen: number
}

const UNAUTHORIZED =
  'The backend requires an API key. Set VITE_LECGAP_API_KEY in frontend-react/.env ' +
  '(and LECGAP_API_KEY on the server) — the app cannot reach the API without it.'

/**
 * `defaults` lets a caller (notably a test asserting on a failure) skip the
 * app's single retry. The retry is right in production — a dropped connection
 * should not blank a panel — but a test that deliberately provokes a 401 should
 * not sit out React Query's ~1s backoff to reach its assertion.
 */
export function createQueryClient(
  defaults?: Partial<DefaultOptions>,
): QueryClient {
  // `QueryCache({ onError })` / `MutationCache({ onError })` is the documented
  // v5 interception point. (Subscribing to the cache and filtering for an
  // "error" event does not work — v5's notify events are added/removed/updated/
  // observerResultsUpdated/observerOptionsUpdated, with the error only as a
  // field on the updated query's state.)
  const raiseIfUnauthorized = (error: unknown) => {
    if (error instanceof LecGapApiError && error.status === 401) {
      setAuthBanner(UNAUTHORIZED)
    }
  }

  return new QueryClient({
    queryCache: new QueryCache({ onError: raiseIfUnauthorized }),
    mutationCache: new MutationCache({ onError: raiseIfUnauthorized }),
    defaultOptions: {
      queries: {
        staleTime: 1000 * 10,
        gcTime: 1000 * 60 * 5,
        retry: 1,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: 0 },
      ...defaults,
    },
  })
}

let banner: AuthBanner = { message: null, lastSeen: 0 }
const listeners = new Set<() => void>()

function setAuthBanner(message: string | null): void {
  banner = { message, lastSeen: message ? Date.now() : 0 }
  for (const l of listeners) l()
}

export function getAuthBanner(): AuthBanner {
  return banner
}

/** Subscribe to the banner. Returns an unsubscribe. */
export function subscribeAuthBanner(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Clear it, e.g. after the key is corrected. */
export function clearAuthBanner(): void {
  setAuthBanner(null)
}

/** True when an error is the "needs a key" case. */
export function isUnauthorized(err: unknown): boolean {
  return err instanceof LecGapApiError && err.status === 401
}
