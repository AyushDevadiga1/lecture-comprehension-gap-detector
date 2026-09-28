import '@testing-library/jest-dom'
import { afterEach, beforeEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

/**
 * jsdom does not implement these, and MUI / the DAG renderer (Wave 3) touch
 * them on mount. Stubbed once here rather than per test file.
 */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

class ObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

globalThis.ResizeObserver ??= ObserverStub as unknown as typeof ResizeObserver
globalThis.IntersectionObserver ??= ObserverStub as unknown as typeof IntersectionObserver

/**
 * A default `fetch` that throws.
 *
 * The previous suite had one test that rendered the real `App`; the Navbar's
 * course query fired a live `fetch` against jsdom's default origin, failed, and
 * was swallowed by React Query after a retry — the test passed, and all 1.1s of
 * its runtime was that request timing out. A throw-by-default global means a
 * test that forgets `mockFetch` fails immediately and by name, instead of
 * passing for the wrong reason.
 *
 * Re-asserted in `beforeEach` rather than set once at module load: a plain
 * function (not a `vi.fn`) so `vi.restoreAllMocks()` cannot blank its
 * implementation, and re-armed per test so a previous test's teardown cannot
 * leave a test with a silent no-op `fetch`.
 */
const failClosedFetch = async (input: RequestInfo | URL): Promise<Response> => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  throw new Error(
    `Unstubbed fetch to ${url}. Call mockFetch([...]) from src/test/fetchMock.ts, ` +
      `or pass routes to renderWithProviders.`,
  )
}

beforeEach(() => {
  globalThis.fetch = failClosedFetch
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
