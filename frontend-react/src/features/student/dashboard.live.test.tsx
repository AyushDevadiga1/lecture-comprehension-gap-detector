/**
 * LIVE tier — the app rendering itself from a real backend.
 *
 * `read.live.test.ts` proves the client can talk to a server. This proves the
 * thing that actually matters to a person using the app: that real server
 * responses become visible text in the real components, with no mocked
 * transport anywhere in the path.
 *
 * Every assertion is anchored on a sentinel that exists ONLY in
 * `scripts/seed_live_db.py`, so a pass cannot be an accident of the real
 * database happening to look similar.
 *
 * ## What this tier found
 *
 * The first run of this file failed on `SSE Live` while the feed was provably
 * streaming two jobs. The cause was `JobFeed.connect()` assigning `this.sink`
 * and then calling `disconnect()`, which nulls it — so `publish()`'s
 * `this.sink?.(next)` was permanently a no-op and the job feed had never once
 * reached the React Query cache. The UI sat at "Disconnected" with an empty job
 * list for the life of the page. All 17 existing feed tests missed it because
 * they assert through `subscribe()` and connect without a sink.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { App } from '../../App'
import { renderWithProviders } from '../../test/render'
import { createQueryClient } from '../../lib/authBanner'
import { useAppStore } from '../../store/useAppStore'
import { enableLiveBackend } from '../../test/live/enableLiveBackend'

enableLiveBackend()

/**
 * Render the real app against a real backend.
 *
 * Uses `createQueryClient()` — the APP's own factory — rather than the
 * `createTestQueryClient()` the mocked tier uses, and the difference is not
 * cosmetic. That helper sets `gcTime: 0`, and the job feed writes its snapshot
 * with `setQueryData` into a query that has **no Query observer**: the
 * components read it through `useSyncExternalStore` over the cache, not through
 * `useQuery`. With zero observers, `gcTime: 0` garbage-collects the entry the
 * instant it is created, `getSnapshot` finds nothing, and every component falls
 * back to `EMPTY_STATE` — the UI shows "Disconnected" with an empty job list
 * while the feed streams happily in the background. The app's real client uses
 * `gcTime: 5 * 60 * 1000`, so this is a harness artefact, not a product bug.
 *
 * It is, however, a third blind spot of the same family: `gcTime: 0` is why the
 * mocked suite could never have caught the `connect()` sink bug either.
 */
function renderApp() {
  const queryClient = createQueryClient()
  window.history.pushState({}, '', '/student')
  renderWithProviders(<App client={queryClient} />, { withProviders: false })
  return { queryClient }
}

const body = () => document.body.textContent ?? ''

beforeEach(() => {
  // zustand is module-global; without a reset the drawer keeps whatever state
  // the previous test left it in.
  useAppStore.setState({ selectedCourseId: 'ml', jobDrawerOpen: false })
})

describe('live: the student dashboard renders real server data', () => {
  it('lists the seeded lectures, which exist only in the throwaway database', async () => {
    renderApp()

    // Seeded titles. If they appear, the response really came from the live
    // backend and really was rendered by the real component.
    expect(await screen.findByText('Linear Regression')).toBeInTheDocument()
    expect(await screen.findByText('Multiple Regression')).toBeInTheDocument()
  })

  it('shows the snapshot counts the seeded database actually implies', async () => {
    renderApp()
    await screen.findByText('Linear Regression')

    // Seed for 'ml': 2 lectures both ready, 3 concepts, a 2-edge graph,
    // 2 clips of which both are ok. Each string is the literal the component
    // renders, so a wrong count cannot pass.
    await waitFor(() => {
      expect(body()).toContain('2 (2 ready)') // Total Lectures
      expect(body()).toContain('2 Edges') // Prerequisite Graph
      expect(body()).toContain('2 / 2 OK') // Video Clips Cut
    })

    // Extracted Concepts is a bare number next to its own caption, so scope it.
    const conceptCard = screen.getByText('Extracted Concepts').closest('div')!
    expect(conceptCard.textContent).toContain('3')
  })

  it('never renders a filesystem path from a clip payload', async () => {
    renderApp()
    await screen.findByText('Linear Regression')

    // ARCHITECTURE §3: no path→URL mapper on the client. The seed stores
    // 'clips/1/linear.mp4'; if that string reached the DOM the contract is
    // broken, whatever the unit tests say.
    await waitFor(() => {
      expect(body()).not.toContain('clips/1/')
      expect(body()).not.toContain('\\data\\processed')
    })
  })
})

describe('live: the SSE feed reaches the UI', () => {
  it('shows the seeded in-flight job, delivered over a real stream', async () => {
    renderApp()
    // Closed by default; a real user opens it from the Navbar.
    useAppStore.getState().setJobDrawerOpen(true)

    // The chip label is driven by feed mode, and mode only becomes 'stream'
    // after a real SSE frame is parsed AND reaches the cache. This is the app's
    // central claim, and the assertion that was impossible to make with a fake
    // transport.
    expect(await screen.findByText('SSE Live', {}, { timeout: 20_000 })).toBeInTheDocument()

    // The seeded RUNNING job. `useActiveJobs` filters terminal rows out, so
    // this can only be on screen if a live snapshot was parsed and rendered.
    //
    // Asserted on the document text rather than with `findByText`: JobDrawer
    // renders the detail as a second text node beside `jobGuidance(...)` inside
    // one <Typography> (JobDrawer.tsx:131-132), and a substring matcher cannot
    // match across sibling text nodes.
    await waitFor(
      () => {
        expect(body()).toContain('Persisting concepts, passages, and spoken links')
        expect(body()).toMatch(/#\d+/) // the card header, "#<id> • extract"
        expect(body()).toContain('Multiple Regression') // the job's title
      },
      { timeout: 20_000 },
    )

    // If this fails, the two things worth knowing are `jobFeed`'s own state
    // (`mode` / `jobs.length`) and whether `queryClient.getQueryCache()` holds
    // a `["jobs","ml"]` entry. The first says whether the stream arrived; the
    // second says whether it reached the cache. They diverge exactly when the
    // feed is live but nothing renders — which is the failure this file exists
    // to catch, so they are worth printing when it goes red.
  })

  it('disables actions only on the lecture that has a job in flight', async () => {
    renderApp()
    await screen.findByText('Linear Regression')

    // Two rows: the seeded `prob` lecture is correctly filtered out by
    // `course_id` (it was returned in full until 2026-09-29, when this file
    // found the route had no such parameter). One of the two carries the running
    // job, so exactly one "Extract Concepts" button may be disabled. This is the
    // double-fire guard, driven by a real feed rather than a hand-built busy set.
    await waitFor(() => {
      const buttons = screen.getAllByRole('button', { name: 'Extract Concepts' })
      expect(buttons).toHaveLength(2)
      const disabled = buttons.filter((b) => (b as HTMLButtonElement).disabled)
      const enabled = buttons.filter((b) => !(b as HTMLButtonElement).disabled)
      expect(disabled).toHaveLength(1)
      expect(enabled).toHaveLength(1)
    })
  })
})
