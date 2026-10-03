import React from 'react'
import { Box } from '@mui/material'
import { ErrorAlert } from './ErrorAlert'
import { errorMessage } from '../../api/client'

/**
 * Catches a render throw and shows it, instead of unmounting the whole app.
 *
 * ## Why this file had to exist
 *
 * Everything else in this codebase fails *well*. A 401 raises one banner rather
 * than a dead "no courses" state (`lib/authBanner.ts`). A dead worker is called
 * out after a six-hour backstop (`lib/jobStalls.ts`). An aborted upload settles
 * its promise (`api/client.ts:192`). A malformed SSE frame is skipped, never
 * fatal (the policy at the top of the feed module). None of that helps when a
 * component throws while rendering, because React unmounts the entire tree
 * below the nearest boundary and there was no boundary — so one bad `sx`, one
 * undefined dereference in a 729-line dashboard, and the user gets a white page
 * with no message, no navbar, and no way back except a reload.
 *
 * That is the same failure the 401 work was about, one level up: a state that
 * *misleads* the reader about what is wrong. A blank page says "the app is
 * broken" and nothing more; this says what broke and offers the one action that
 * fixes it.
 *
 * ## Where the boundaries go, and why there are two
 *
 *   - **Root, in `main.tsx`** — outside every provider, so it also catches a
 *     failure in `QueryClientProvider`, `AppTheme` or the router. Its fallback
 *     is degraded on purpose: if `AppTheme` never mounted, the `--lgc-*`
 *     custom properties `ErrorAlert` tints with were never written, so those
 *     washes resolve to nothing and MUI's own Alert styling carries the panel.
 *     Imperfect, and much better than the alternative.
 *   - **Around `<Outlet/>`, in `AppLayout`** — inside the theme and the router,
 *     so a dashboard that throws costs you the dashboard and nothing else. The
 *     navbar, the job drawer and the 401 banner all survive, which is what makes
 *     this the boundary that matters: the drawer is often the only way to see
 *     what went wrong.
 *
 * ## `resetKeys`
 *
 * A boundary that has caught stays caught, so without this a single transient
 * throw would poison a route for the rest of the session even after the user
 * navigated away. `AppLayout` passes the selected course, so switching course
 * re-arms the panel and the new content gets a clean render.
 *
 * ## What this does not catch
 *
 * React boundaries do not catch throws in event handlers, in `setTimeout`
 * callbacks, or in promises. Those are handled where they happen: the SSE
 * callbacks are wrapped inside the feed module, the mutation and upload paths
 * `try`/`catch` into an `ErrorAlert`, and React Query's own cache-level
 * handlers own the 401. This is the last line, not the only one.
 */

export interface ErrorBoundaryProps {
  children: React.ReactNode
  /** Heading for the fallback panel. Say *what* broke, not "Error". */
  title?: string
  /**
   * When any of these changes identity, a caught error is cleared.
   *
   * This is the difference between "this route is broken until you reload" and
   * "this route is broken until you go somewhere else".
   */
  resetKeys?: readonly unknown[]
  /** Escape hatch for a caller that wants its own fallback UI. */
  fallback?: (error: Error, reset: () => void) => React.ReactNode
  /** Notified once per caught error, after it has been recorded. */
  onError?: (error: Error, info: React.ErrorInfo) => void
}

interface ErrorBoundaryState {
  error: Error | null
}

/** True when any entry differs, so the boundary knows to re-arm. */
function resetKeysChanged(a: readonly unknown[], b: readonly unknown[]): boolean {
  if (a.length !== b.length) return true
  return a.some((value, i) => !Object.is(value, b[i]))
}

/**
 * A non-Error throw still has to become something renderable. `null`/`undefined`
 * would render an empty panel, which is the blank-page failure in miniature.
 */
function toError(thrown: unknown): Error {
  if (thrown instanceof Error) return thrown
  const text = typeof thrown === 'string' ? thrown : JSON.stringify(thrown)
  return new Error(text || 'Unknown error')
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: toError(error) }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // `console.error` is the one console method the lint config allows, and this
    // is the one place it is right: an error that unmounts a view without a
    // trace in the console cannot be diagnosed from a screenshot.
    console.error('[ErrorBoundary] render failed', error, info.componentStack)
    this.props.onError?.(error, info)
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    if (this.state.error === null) return
    const before = prevProps.resetKeys ?? []
    const after = this.props.resetKeys ?? []
    if (resetKeysChanged(before, after)) this.setState({ error: null })
  }

  /** Re-render the children. The cheap recovery: state is untouched. */
  private readonly reset = (): void => this.setState({ error: null })

  render(): React.ReactNode {
    const { error } = this.state
    if (error === null) return this.props.children

    const { fallback, title = 'Something went wrong' } = this.props
    if (fallback) return fallback(error, this.reset)

    return (
      <Box role="group" aria-label={title} sx={{ p: 3 }}>
        <ErrorAlert error={errorMessage(error, error.message)} title={title} onRetry={this.reset} />
      </Box>
    )
  }
}