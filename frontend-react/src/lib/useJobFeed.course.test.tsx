import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useEffect, useState } from 'react'
import { waitFor } from '@testing-library/react'
import { QueryClient } from '@tanstack/react-query'
import { useJobFeedConnection, useJobs } from './useJobFeed'
import { queryKeys } from './queryKeys'
import { jobFeed } from './jobFeed'
import type { FeedState } from './jobFeed'
import type { JobOut } from '../api/types'
import { renderWithProviders } from '../test/render'

/**
 * The regression four e2e tests were red for.
 *
 * `useJobFeedConnection` used to build its sink once, in a ref, on first render.
 * That sink wrote every snapshot to `queryKeys.jobs(courseId ?? '')`. On a first
 * visit `selectedCourseId` is `null` — the Navbar auto-selects the first course
 * only after `GET /courses` resolves — so the feed reconnected for `ml` while
 * the sink went on writing to `['jobs', '']`. Every reader read `['jobs', 'ml']`,
 * found nothing, and fell back to `EMPTY_STATE` (`mode: 'starting'`, no jobs):
 * the drawer sat on "Connecting" with an empty list, against a backend that was
 * streaming correctly the whole time.
 *
 * Why 328 unit tests missed it: **every one of them started with a course already
 * selected**, so the stale closure always happened to hold the right value. The
 * bug lived only in the `null -> 'ml'` transition, which only a real browser
 * booting against a real `/courses` performs. That is the argument for keeping
 * the Playwright tier; these are the unit-shaped memory of it.
 */

/** Drives the connection for a course the test controls. */
function Connect({ courseId }: { courseId: string | null }): null {
  useJobFeedConnection(courseId)
  return null
}

/** Reads the feed exactly the way JobDrawer does — through the query cache. */
function Read({ courseId }: { courseId: string | null }) {
  const { mode, jobs } = useJobs(courseId)
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="count">{jobs.length}</span>
    </div>
  )
}

const job = {
  id: 7,
  kind: 'extract',
  status: 'running',
  course_id: 'ml',
  lecture_id: 2,
  title: 'Multiple Regression',
  stage: 'extracting',
  detail: 'Persisting concepts...',
  progress_pct: 70,
  error: null,
  created_at: '2026-01-01T00:00:00Z',
  started_at: null,
  finished_at: null,
  heartbeat_at: null,
  duration_s: null,
  terminal: false,
} as JobOut

/**
 * Intercept the sink `useJobFeedConnection` installs per connection, keyed by the
 * course it was installed for.
 *
 * Spying on `connect` rather than reaching into the feed's private `sink` is
 * deliberate: what is under test is the wiring from *this hook* into the query
 * cache, and that wiring *is* the callback. The feed's own parsing is covered by
 * `jobFeed.test.ts`. Keying by course is what lets a test deliver a frame to the
 * connection it means, instead of whichever connected last.
 */
function captureConnects() {
  const sinks = new Map<string, (state: FeedState) => void>()
  vi.spyOn(jobFeed, 'connect').mockImplementation((courseId: string | null | undefined, sink) => {
    sinks.set(courseId ?? '', (state) => sink?.(state))
  })
  return {
    connectedFor: (courseId: string) => sinks.has(courseId),
    /** Play the part of a parsed SSE frame for one specific connection. */
    frame: (courseId: string, jobs: JobOut[], mode: FeedState['mode'] = 'stream') => {
      const sink = sinks.get(courseId)
      if (!sink) {
        throw new Error(`no connection for course "${courseId}"; connected for: [${[...sinks.keys()]}]`)
      }
      sink({ jobs, mode, changeToken: jobs.length })
    },
  }
}

const text = (testid: string): string =>
  document.querySelector(`[data-testid="${testid}"]`)?.textContent ?? ''
const count = (testid: string): number => Number(text(testid))

/**
 * Render with a cache that does **not** expire entries.
 *
 * `createTestQueryClient()` sets `gcTime: 0`, which is right for most tests and
 * fatal for this one. The feed's sink calls `setQueryData` for a key that no
 * `useQuery` observer owns — `useJobs` reads the cache through
 * `useSyncExternalStore`, which subscribes to the cache but never becomes an
 * observer. With `gcTime: 0` such an entry is collected the instant it is
 * written, so `getQueryData` returns `undefined` and every reader sees
 * `EMPTY_STATE`.
 *
 * That is worth stating plainly, because it means this class of bug is
 * *unreachable* from a unit test written against the shared helper: the cache
 * cannot retain the very write it needs to assert on. The app's real client uses
 * `gcTime: 5 * 60 * 1000`, which is why the bug was invisible in the browser and
 * visible only to Playwright.
 */
function renderWithRetainingCache(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: 0 } },
  })
  return renderWithProviders(ui, { queryClient })
}

/**
 * Deliver a frame, then wait for the sink's coalescing window to close.
 *
 * `createJobsSink` defers the cache write to the next animation frame (OPEN
 * decision #1 — one write per painted frame), so `write()` is not synchronous.
 * Asserting straight after `frame()` tests the scheduler's timing rather than
 * the wiring, and passes or fails by luck.
 */
async function frameFor(
  feed: ReturnType<typeof captureConnects>,
  queryClient: QueryClient,
  courseId: string,
  jobs: JobOut[],
  mode: FeedState['mode'] = 'stream',
): Promise<void> {
  feed.frame(courseId, jobs, mode)
  await waitFor(() =>
    expect(queryClient.getQueryData(queryKeys.jobs(courseId))).toBeDefined(),
  )
}

describe('useJobFeedConnection — which course key the sink writes to', () => {
  let feed: ReturnType<typeof captureConnects>

  beforeEach(() => {
    // Start disconnected so the module-level connection ref-count cannot leak
    // between tests, then intercept `connect`.
    jobFeed.disconnect()
    feed = captureConnects()
  })

  afterEach(() => {
    jobFeed.disconnect()
  })

  it('writes under the course selected at connect time', async () => {
    const { queryClient } = renderWithRetainingCache(
      <>
        <Connect courseId="ml" />
        <Read courseId="ml" />
      </>,
    )

    await frameFor(feed, queryClient, 'ml', [job])

    expect(queryClient.getQueryData(queryKeys.jobs('ml'))).toBeDefined()
    expect(text('mode')).toBe('stream')
    expect(count('count')).toBe(1)
  })

  it('follows the course when it is selected AFTER the first render', async () => {
    // The exact failure: `null` on mount, 'ml' once the course list resolves.
    function AutoSelect() {
      const [courseId, setCourseId] = useState<string | null>(null)
      useEffect(() => {
        const t = setTimeout(() => setCourseId('ml'), 0)
        return () => clearTimeout(t)
      }, [])
      return (
        <>
          <Connect courseId={courseId} />
          <Read courseId={courseId} />
        </>
      )
    }

    const { queryClient } = renderWithRetainingCache(<AutoSelect />)

    // The Navbar's auto-select has landed and the feed reconnected for 'ml'.
    await waitFor(() => expect(feed.connectedFor('ml')).toBe(true))

    await frameFor(feed, queryClient, 'ml', [job])

    // Before the fix the sink was the one built during the `null` render, so this
    // landed in `['jobs','']` and both reads below stayed on EMPTY_STATE.
    expect(queryClient.getQueryData(queryKeys.jobs('ml'))).toMatchObject({ mode: 'stream' })
    expect(text('mode')).toBe('stream')
    expect(count('count')).toBe(1)
  })

  it('leaves no populated snapshot under the empty-course key', async () => {
    // The fingerprint of the old bug: a populated `['jobs','']` means something
    // is still writing snapshots for a course nobody asked for.
    function AutoSelect() {
      const [courseId, setCourseId] = useState<string | null>(null)
      useEffect(() => {
        const t = setTimeout(() => setCourseId('ml'), 0)
        return () => clearTimeout(t)
      }, [])
      return <Connect courseId={courseId} />
    }

    const { queryClient } = renderWithRetainingCache(<AutoSelect />)
    await waitFor(() => expect(feed.connectedFor('ml')).toBe(true))

    await frameFor(feed, queryClient, 'ml', [job])

    const stray = queryClient.getQueryData(queryKeys.jobs(''))
    expect(stray == null || (stray as FeedState).jobs.length === 0).toBe(true)
  })

  it('does not leak one course jobs into another course key', async () => {
    function Switcher() {
      const [courseId, setCourseId] = useState<string | null>('ml')
      useEffect(() => {
        const t = setTimeout(() => setCourseId('prob'), 0)
        return () => clearTimeout(t)
      }, [])
      return (
        <>
          <Connect courseId={courseId} />
          <Read courseId={courseId} />
        </>
      )
    }

    const { queryClient } = renderWithRetainingCache(<Switcher />)
    await frameFor(feed, queryClient, 'ml', [job])
    expect(queryClient.getQueryData(queryKeys.jobs('ml'))).toBeDefined()

    await waitFor(() => expect(feed.connectedFor('prob')).toBe(true))
    await frameFor(feed, queryClient, 'prob', [], 'starting')

    // 'prob' is a fresh key and must not inherit 'ml' rows.
    expect(queryClient.getQueryData(queryKeys.jobs('prob'))).toBeDefined()
    expect(text('mode')).toBe('starting')
    expect(count('count')).toBe(0)
  })
})