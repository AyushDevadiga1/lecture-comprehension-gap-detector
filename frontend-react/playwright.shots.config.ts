/**
 * Config for `npm run shots` only.
 *
 * The screenshot spec is a *review* tool, not a gate: it exists so a person can
 * look at the real app, and its output is scratch to be deleted afterwards. It
 * is excluded from `npm run test:e2e` in `playwright.config.ts` so that running
 * the gate does not quietly regenerate `screenshots/` on every invocation.
 *
 * Everything else — the backend, the Vite dev server, the ports, the seeded
 * throwaway database — is inherited unchanged, so what gets reviewed is the same
 * app the gate tests.
 */

import base from './playwright.config'

export default {
  ...base,
  testIgnore: undefined,
  testMatch: '**/shots.spec.ts',
}
