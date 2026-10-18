import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { App } from './App'
import { mockFetch } from './test/fetchMock'
import { createTestQueryClient } from './test/queries'
import { renderWithProviders } from './test/render'

/**
 * The app shell: brand, role navigation, and which dashboard each route mounts.
 *
 * Every request here is served by an explicit route table, so this suite is
 * hermetic — it used to render the real Navbar query against jsdom's origin
 * and pass only because React Query swallowed the rejection.
 */

const courses = [
  { course_id: 'ml', total_lectures: 2, ready_lectures: 2, total_concepts: 24, has_graph: true, node_count: 22, edge_count: 10 },
  { course_id: 'prob', total_lectures: 1, ready_lectures: 1, total_concepts: 51, has_graph: true, node_count: 46, edge_count: 73 },
]

const emptySnapshot = {
  exists: true,
  course_id: 'ml',
  lectures: { total: 0, ready: 0, uploaded: 0, transcribing: 0, error: 0 },
  concepts: 0,
  graph: { has: false, nodes: 0, edges: 0 },
  clips: { cut: 0, ok: 0 },
  quiz: { questions: 0, respondents: 0 },
  in_flight: [],
}

const emptyStats = { course_id: 'ml', heatmap: [], divergence: [], taught_order: [], learned_order: [] }

const routes = [
  { path: '/courses', json: courses },
  { path: '/courses/ml/snapshot', json: emptySnapshot },
  { path: '/courses/ml/stats', json: emptyStats },
  { path: '/lectures', json: [] },
  { path: /^\/jobs\/?$/, json: { jobs: [] } },
  { path: '/usage', json: { services: {} } },
]

describe('App shell', () => {
  it('renders the brand and both role links', async () => {
    const fetchMock = mockFetch(routes)
    renderWithProviders(<App client={createTestQueryClient()} />, { withProviders: false })

    expect(screen.getByText('LecGap')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Overview/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Analytics/i })).toBeInTheDocument()

    // The course picker comes from GET /courses — prove it was served, not skipped.
    await waitFor(() => expect(fetchMock.callsTo('GET', '/courses')).toHaveLength(1))
  })

  it('redirects the index route to the student dashboard', async () => {
    mockFetch(routes)
    window.history.pushState({}, '', '/')
    renderWithProviders(<App client={createTestQueryClient()} />, { withProviders: false })

    await waitFor(() => {
      expect(window.location.pathname).toBe('/student/overview')
    })
  })

  it('mounts the faculty dashboard on /faculty', async () => {
    mockFetch(routes)
    window.history.pushState({}, '', '/faculty')
    renderWithProviders(<App client={createTestQueryClient()} />, { withProviders: false })

    // The page heading, not the nav link — both contain "Faculty insights".
    // The route is lazy now: the first import of a view can exceed waitFor's
    // 1s default, so this waits on the chunk rather than on a render.
    await waitFor(
      () => {
        expect(screen.getByRole('heading', { name: /Faculty insights: ML/i })).toBeInTheDocument()
      },
      { timeout: 8000 },
    )
  }, 20000)

  it('shows a not-found page for an unknown route', async () => {
    mockFetch(routes)
    window.history.pushState({}, '', '/nope')
    renderWithProviders(<App client={createTestQueryClient()} />, { withProviders: false })

    await waitFor(() => {
      expect(screen.getByText('404')).toBeInTheDocument()
    })
  })
})
