import { createQueryClient } from './authBanner'

/**
 * The app-wide QueryClient.
 *
 * Built by `createQueryClient()` in `lib/authBanner.ts` so the 401 interception
 * is installed exactly once, at the single place every read passes through (§6).
 * Re-declaring the defaults here would let the two drift.
 *
 * This module used to be a three-line re-export of `createQueryClient` from
 * `authBanner` plus `queryClient` from a separate `appClient.ts`, whose entire
 * contents were `export const queryClient = createQueryClient()`. Two files and
 * an indirection to hold one object, with `App.tsx` importing through both.
 * Nothing imported `appClient` directly; it was reachable only from here.
 */
export { createQueryClient }

/** The app-wide client. Production code uses this; tests use their own. */
export const queryClient = createQueryClient()