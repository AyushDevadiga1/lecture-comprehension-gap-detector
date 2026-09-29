/**
 * Opt a test file into the REAL backend.
 *
 * `src/test/setup.ts` arms a fail-closed `fetch` in a global `beforeEach` so a
 * test that forgets `mockFetch` fails loudly instead of quietly hitting the
 * network. That guard is worth keeping, but the live tier exists precisely to
 * use the real one, so it has to be undone deliberately.
 *
 * Calling `enableLiveBackend()` registers a `beforeEach` that restores the
 * genuine `fetch`. Because `setup.ts` registered first, and `beforeEach`
 * ordering is registration order, this one wins. It only wins for files that
 * asked for it, so the mocked tier keeps its fail-closed guarantee.
 *
 * The real `fetch` is captured at module load, before any `beforeEach` can
 * replace it, so restoring it is just putting back the original reference.
 *
 * Not named `useLiveBackend`: the react-hooks lint rule treats a `use` prefix
 * as a hook and rejects a top-level call, which is correct for hooks and wrong
 * for a test helper.
 */

import { beforeEach } from 'vitest'

/** Node's undici fetch, captured before any test can swap it out. */
const REAL_FETCH = globalThis.fetch.bind(globalThis)

export function enableLiveBackend(): void {
  beforeEach(() => {
    globalThis.fetch = REAL_FETCH
  })
}

/** The live backend's origin, for a direct assertion or a media URL. */
export function liveBaseUrl(): string {
  const base = process.env.VITE_LECGAP_API_URL
  if (!base) throw new Error('VITE_LECGAP_API_URL unset: setupLive.ts did not run')
  return base
}
