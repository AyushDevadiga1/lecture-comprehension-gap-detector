/**
 * The app-wide QueryClient.
 *
 * Built by `createQueryClient()` in `lib/authBanner.ts` so the 401 interception
 * is installed exactly once, at the single place every read passes through (§6).
 * Re-declaring the defaults here would let the two drift.
 */
export { createQueryClient } from './authBanner'
export { queryClient } from './appClient'
