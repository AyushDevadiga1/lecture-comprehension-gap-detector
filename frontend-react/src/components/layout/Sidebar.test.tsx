import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient } from '@tanstack/react-query'
import { Sidebar } from './Sidebar'
import { renderWithProviders } from '../../test/render'
import { mockFetch } from '../../test/fetchMock'
import { useAppStore } from '../../store/useAppStore'
import { queryKeys } from '../../lib/queryKeys'
import type { FeedState } from '../../lib/jobFeed'
import type { JobOut } from '../../api/types'

/**
 * The sidebar is the primary navigation and the only place the shell reads
 * ambient state. Three things are worth pinning:
 *
 *  1. every nav item renders, from one table — a view cannot be reachable in
 *     the sidebar and absent from the routes (the table is shared),
 *  2. the current route is announced (`aria-current`), not merely coloured,
 *  3. the footer's job count and feed label come from the cache, so the sidebar
 *     never opens a second connection and never fetches /jobs.
 */

const courses = [
  {
    course_id: 'ml',
    total_lectures: 3,
    ready_lectures: 3,
    total_concepts: 181,
    has_graph: true,
    node_count: 150,
    edge_count: 170,
  },
]

const usagePayload = {
  services: {
    'groq.chat': { remaining_requests: 4812, reset_in_s: 720 },
    'groq.whisper': { remaining_requests: 71 },
  },
}

const job = (id: number, status = 'running'): JobOut =>
  ({
    id,
    kind: 'extract',
    status,
    course_id: 'ml',
    lecture_id: 1,
    title: 'Linear Regression',
    stage: 'extracting',
    detail: null,
    progress_pct: 40,
    error: null,
    // Recent, deliberately: `useActiveJobs` drops anything past the six-hour
    // backstop (lib/jobStalls), so a fixed date would make a live job expire.
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: null,
    heartbeat_at: new Date().toISOString(),
    duration_s: null,
    terminal: false,
  }) as JobOut

/** A client that keeps cache entries: no observers own the jobs key. */
function retainingClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } },
  })
}

function renderSidebar(opts: { route?: string; feed?: FeedState; jobs?: JobOut[] } = {}) {
  const client = retainingClient()
  if (opts.feed) client.setQueryData(queryKeys.jobs('ml'), opts.feed)
  const mock = mockFetch([
    { path: '/courses', json: courses },
    { path: '/usage', json: usagePayload },
  ])
  const view = renderWithProviders(<Sidebar />, {
    queryClient: client,
    route: opts.route ?? '/student/overview',
  })
  return { mock, view, client }
}

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: 'ml', base: 'dark' })
})

describe('Sidebar', () => {
  it('renders every section from the nav table', async () => {
    renderSidebar()
    const nav = await screen.findByRole('navigation', { name: 'Sections' })

    for (const group of ['Student', 'Faculty', 'System']) {
      expect(within(nav).getByText(group)).toBeInTheDocument()
    }
    const links = within(nav).getAllByRole('link')
    expect(links).toHaveLength(13)
    for (const label of ['Overview', 'Concept map', 'Quiz', 'Heatmap', 'Jobs', 'System & quota']) {
      expect(within(nav).getByText(label)).toBeInTheDocument()
    }
  })

  it('announces the current route rather than only colouring it', async () => {
    renderSidebar({ route: '/student/map' })
    const nav = await screen.findByRole('navigation', { name: 'Sections' })

    await waitFor(() => {
      expect(within(nav).getByRole('link', { name: /Concept map/ })).toHaveAttribute(
        'aria-current',
        'page',
      )
    })
    // And exactly one item claims to be current.
    expect(within(nav).getAllByRole('link').filter((l) => l.getAttribute('aria-current') === 'page')).toHaveLength(1)
  })

  it('shows the active job count from the cache, not from a new request', async () => {
    renderSidebar({
      feed: { jobs: [job(1), job(2)], mode: 'stream', changeToken: 2 },
    })

    expect(await screen.findByText('2')).toBeInTheDocument()
    // The two jobs are also named in the footer summary.
    expect(screen.getByText(/2 jobs/)).toBeInTheDocument()
  })

  it('describes a polled feed as polling, not as disconnected', async () => {
    renderSidebar({ feed: { jobs: [job(1)], mode: 'poll', changeToken: 1 } })
    expect(await screen.findByText(/Polling/)).toBeInTheDocument()
  })

  it('describes a dead feed as disconnected', async () => {
    renderSidebar({ feed: { jobs: [], mode: 'unavailable', changeToken: 0 } })
    expect(await screen.findByText(/Disconnected/)).toBeInTheDocument()
  })

  it('renders the quota line from /usage', async () => {
    renderSidebar()
    expect(await screen.findByText('Groq 4,812 req · 71 whisper · resets 12m')).toBeInTheDocument()
  })

  it('toggles the theme base from the footer', async () => {
    const user = userEvent.setup()
    renderSidebar()

    await user.click(await screen.findByRole('button', { name: 'Switch to light theme' }))
    expect(useAppStore.getState().base).toBe('light')
    expect(await screen.findByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument()
  })
})
