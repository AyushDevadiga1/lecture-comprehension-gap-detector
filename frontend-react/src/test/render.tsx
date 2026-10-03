import type { ReactElement, ReactNode } from 'react'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { AppProviders } from '../AppProviders'
import { createTestQueryClient } from './queries'

/**
 * Render a component with the providers it expects.
 *
 * ## The providers are the app's, not a copy
 *
 * This used to build its own stack — `QueryClientProvider > ThemeProvider(
 * buildTheme()) + CssBaseline > MemoryRouter` — which had already drifted from
 * `App.tsx`: it swapped `AppTheme` for a bare `ThemeProvider`, so `applyCssVariables`
 * never ran and no test ever exercised the real theme path. It is now
 * `AppProviders`, the same component the app renders, with only the router
 * differing. See `src/AppProviders.tsx` for why that difference is legitimate
 * and the rest was not.
 *
 * `App` owns its own providers (and takes an optional `client`), so pass
 * `withProviders: false` when testing it directly — wrapping it again would put
 * a second QueryClientProvider outside the one it actually uses, and the client
 * returned here would silently not be the one in use.
 */
export interface RenderOptions {
  queryClient?: ReturnType<typeof createTestQueryClient>
  /** Wraps in AppProviders + MemoryRouter. Default true. */
  withProviders?: boolean
  /** Initial route for MemoryRouter, e.g. '/faculty'. */
  route?: string
}

export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}) {
  const { queryClient = createTestQueryClient(), withProviders = true, route } = options
  const user = userEvent.setup()

  if (!withProviders) {
    return { ...render(ui), user, queryClient }
  }

  const Providers = ({ children }: { children: ReactNode }) => (
    <AppProviders client={queryClient}>
      <MemoryRouter initialEntries={[route ?? '/']}>{children}</MemoryRouter>
    </AppProviders>
  )

  return { ...render(ui, { wrapper: Providers }), user, queryClient }
}
