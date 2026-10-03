import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { AppTheme } from './theme/AppTheme'

/**
 * The provider stack, declared once.
 *
 * ## Why this file exists
 *
 * `App.tsx` and `src/test/render.tsx` each used to hand-roll their own provider
 * stack, and they had already drifted:
 *
 * ```text
 * App.tsx      QueryClientProvider > AppTheme                    > BrowserRouter > Routes
 * render.tsx   QueryClientProvider > ThemeProvider(buildTheme())  > MemoryRouter  > ui
 *                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
 *                     a *different* theme path
 * ```
 *
 * The theme line is the one that mattered. `AppTheme` does two things — it
 * builds the MUI theme from the store's `base`, **and** it writes the
 * `--lgc-*` custom properties onto `documentElement`. The harness used a bare
 * `ThemeProvider`, which does the first and not the second.
 *
 * So no test ever rendered `AppTheme`. A bug in it — the base not following the
 * store, `applyCssVariables` not firing, the two drifting apart — was invisible
 * to all 364 tests and would have shipped on the strength of a green suite. The
 * harness also had `CssBaseline` as a sibling, which the app gets from *inside*
 * `AppTheme` so its `body` override sees the same `page` token; a difference
 * with no reason behind it.
 *
 * Duplication like this does not stay still. It is not that the two stacks
 * *might* diverge — they had.
 *
 * ## What legitimately still differs
 *
 * The router, and only the router: `BrowserRouter` in the app,
 * `MemoryRouter` in tests so a test can start at an arbitrary path without
 * touching `window.history`. That is a real difference in purpose, not an
 * accident, so it stays at the call site rather than being parameterised here.
 */
export function AppProviders({
  client,
  children,
}: {
  /** Injected rather than imported so a test can pass an isolated cache. */
  client: QueryClient
  children: ReactNode
}): ReactNode {
  return (
    <QueryClientProvider client={client}>
      <AppTheme>{children}</AppTheme>
    </QueryClientProvider>
  )
}