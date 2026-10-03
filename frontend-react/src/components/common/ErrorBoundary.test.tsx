import { describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ErrorBoundary } from './ErrorBoundary'
import { renderWithProviders } from '../../test/render'

/**
 * The last line. Everything else in the app fails well — see the module docstring
 * for the catalogue — but nothing caught a render throw, so a bad `sx` or an
 * undefined dereference unmounted the tree and left a blank page with no
 * message, no navbar, and no way back but a reload.
 *
 * These assert the three properties that make a boundary worth having: it
 * catches, it recovers, and it stays caught until something actually changes.
 */

/** Throws on demand, so a test can choose when the tree breaks. */
function Boom({ explode }: { explode: boolean }): React.ReactElement {
  if (explode) throw new Error('dashboard exploded')
  return <p>dashboard content</p>
}

/** The boundary logs to console.error on purpose; keep the run readable. */
function withSilencedError<T>(fn: () => T): T {
  const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
  try {
    return fn()
  } finally {
    spy.mockRestore()
  }
}

describe('ErrorBoundary', () => {
  it('renders its children when nothing throws', () => {
    renderWithProviders(
      <ErrorBoundary>
        <Boom explode={false} />
      </ErrorBoundary>,
    )
    expect(screen.getByText('dashboard content')).toBeInTheDocument()
  })

  it('shows the error instead of a blank page', () => {
    withSilencedError(() =>
      renderWithProviders(
        <ErrorBoundary title="This page failed to render">
          <Boom explode />
        </ErrorBoundary>,
      ),
    )

    // The message, so the reader is told what happened...
    expect(screen.getByText(/dashboard exploded/)).toBeInTheDocument()
    // ...and what it cost them, named by the caller rather than a generic word.
    expect(screen.getByRole('group', { name: 'This page failed to render' })).toBeInTheDocument()
  })

  it('recovers when the user retries', async () => {
    const user = userEvent.setup()

    function Harness() {
      const [explode, setExplode] = useState(true)
      return (
        <>
          <button onClick={() => setExplode(false)}>fix it</button>
          <ErrorBoundary title="Page failed">
            <Boom explode={explode} />
          </ErrorBoundary>
        </>
      )
    }

    withSilencedError(() => renderWithProviders(<Harness />))

    expect(screen.getByText(/dashboard exploded/)).toBeInTheDocument()

    // Change the underlying cause first, so a successful retry is meaningful
    // rather than a re-render that would throw again anyway.
    await user.click(screen.getByRole('button', { name: 'fix it' }))
    await user.click(screen.getByRole('button', { name: /retry/i }))

    expect(screen.queryByText(/dashboard exploded/)).not.toBeInTheDocument()
    expect(screen.getByText('dashboard content')).toBeInTheDocument()
  })

  it('clears a caught error when a resetKey changes identity', async () => {
    // The property that stops one transient throw poisoning a route for the
    // session: AppLayout passes the selected course, so switching course gives
    // the new content a clean render without a reload.
    const user = userEvent.setup()

    function Harness() {
      const [course, setCourse] = useState('ml')
      return (
        <>
          <button onClick={() => setCourse('prob')}>switch course</button>
          <ErrorBoundary title="Page failed" resetKeys={[course]}>
            <Boom explode={course === 'ml'} />
          </ErrorBoundary>
        </>
      )
    }

    withSilencedError(() => renderWithProviders(<Harness />))
    expect(screen.getByText(/dashboard exploded/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'switch course' }))

    expect(screen.getByText('dashboard content')).toBeInTheDocument()
    expect(screen.queryByText(/dashboard exploded/)).not.toBeInTheDocument()
  })

  it('does NOT clear on an unrelated re-render', async () => {
    // The other half of the contract: re-arming is tied to resetKeys, not to
    // "something re-rendered". A boundary that forgave on every render would be
    // a loop, not a recovery.
    const user = userEvent.setup()

    function Harness() {
      const [tick, setTick] = useState(0)
      return (
        <>
          <button onClick={() => setTick((t) => t + 1)}>rerender</button>
          <span data-testid="tick">{tick}</span>
          <ErrorBoundary title="Page failed" resetKeys={['ml']}>
            <Boom explode />
          </ErrorBoundary>
        </>
      )
    }

    withSilencedError(() => renderWithProviders(<Harness />))
    await user.click(screen.getByRole('button', { name: 'rerender' }))

    expect(screen.getByTestId('tick')).toHaveTextContent('1')
    expect(screen.getByText(/dashboard exploded/)).toBeInTheDocument()
  })

  it('reports a non-Error throw as something readable', () => {
    function ThrowsString(): React.ReactElement {
      throw 'a bare string'
    }
    withSilencedError(() =>
      renderWithProviders(
        <ErrorBoundary title="Page failed">
          <ThrowsString />
        </ErrorBoundary>,
      ),
    )
    // An empty panel would be the blank-page failure in miniature.
    expect(screen.getByText(/a bare string/)).toBeInTheDocument()
  })

  it('notifies onError once per caught error', () => {
    const onError = vi.fn()
    withSilencedError(() =>
      renderWithProviders(
        <ErrorBoundary title="Page failed" onError={onError}>
          <Boom explode />
        </ErrorBoundary>,
      ),
    )
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0]).toBeInstanceOf(Error)
  })

  it('honours a caller-supplied fallback', () => {
    withSilencedError(() =>
      renderWithProviders(
        <ErrorBoundary
          title="Page failed"
          fallback={(error) => <p>custom: {error.message}</p>}
        >
          <Boom explode />
        </ErrorBoundary>,
      ),
    )
    expect(screen.getByText(/custom: dashboard exploded/)).toBeInTheDocument()
  })
})