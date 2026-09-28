import type { ReactElement, ReactNode } from 'react'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThemeProvider } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { theme } from '../theme/theme'
import { createTestQueryClient } from './queries'

/**
 * Render a component with the providers it expects.
 *
 * `App` owns its own providers (and takes an optional `client`), so pass
 * `withProviders: false` when testing it directly — wrapping it again would put
 * a second QueryClientProvider outside the one it actually uses, and the client
 * returned here would silently not be the one in use.
 */
export interface RenderOptions {
  queryClient?: ReturnType<typeof createTestQueryClient>
  /** Wraps in ThemeProvider + QueryClientProvider + MemoryRouter. Default true. */
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
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <MemoryRouter initialEntries={[route ?? '/']}>{children}</MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>
  )

  return { ...render(ui, { wrapper: Providers }), user, queryClient }
}
