import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { App } from './App'
import { mockFetch } from './test/fetchMock'
import { renderWithProviders } from './test/render'

/**
 * The regression this whole exercise exists to prevent.
 *
 * Before this, there was no `ErrorBoundary` anywhere in the repo — grep for
 * `ErrorBoundary|componentDidCatch|getDerivedStateFromError` returned nothing.
 * A component that threw while rendering therefore unmounted the entire tree:
 * no navbar, no job drawer, no message, no way back but a reload.
 *
 * The dashboard is a 729-line component built from a `draft.quiz.questions.map`
 * and a dozen `sx` objects, so "a dashboard can throw" is not hypothetical — it
 * is a matter of which field the backend left null.
 *
 * These assert the *placement*, which is the part that is easy to get wrong. A
 * single boundary at the root would also stop the white screen and would still
 * fail every assertion here, because it takes the navbar with it. The boundary
 * that earns its keep is the one around `<Outlet/>`, inside the chrome.
 */

const courses = [
  { course_id: 'ml', total_lectures: 1, ready_lectures: 1, total_concepts: 12, has_graph: true, node_count: 10, edge_count: 4 },
]

const snapshot = {
  exists: true,
  course_id: 'ml',
  lectures: { total: 1, ready: 1, uploaded: 1, transcribing: 0, error: 0 },
  concepts: 12,
  graph: { has: true, nodes: 10, edges: 4 },
  clips: { cut: 0, ok: 0 },
  quiz: { questions: 0, respondents: 0 },
  in_flight: [],
}

const routes = [
  { path: '/courses', json: courses },
  { path: '/courses/ml/snapshot', json: snapshot },
  { path: '/courses/ml/stats', json: { course_id: 'ml', heatmap: [], divergence: [], taught_order: [], learned_order: [] } },
  { path: '/lectures', json: [] },
  { path: /^\/jobs\/?$/, json: { jobs: [] } },
  // A crash on the dashboard's own read: a malformed payload, which is what a
  // schema drift upstream actually looks like from the browser's side.
  { path: '/courses/ml/graph', json: { nodes: [{ id: 'a' }], edges: 'not-an-array' } },
]

/** Render a real page with the console noise of a caught throw suppressed. */
function renderPage(path: string) {
  const spy = console.error
  console.error = () => {}
  try {
    mockFetch(routes)
    window.history.pushState({}, '', path)
    renderWithProviders(<App />, { withProviders: false })
  } finally {
    console.error = spy
  }
}

describe('a render failure does not take down the app shell', () => {
  it('keeps the navbar and both role links when a route throws', async () => {
    renderPage('/student')

    // The chrome is the point: these are what a user needs in order to get out.
    await waitFor(() => expect(screen.getByText('LecGap')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /Student Portal/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Faculty Insights/i })).toBeInTheDocument()
  })

  it('keeps the jobs drawer reachable — often the only way to see what broke', async () => {
    renderPage('/student')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /View Background Jobs/i })).toBeInTheDocument(),
    )
  })

  it('catches the throw in place and keeps the navbar up', async () => {
    // `FacultyDashboard.tsx:88` does `graphData.edges.map(...)` with no guard, so
    // the `edges: 'not-an-array'` route above is a guaranteed render throw —
    // which is what a backend schema drift actually looks like from here. The
    // page must degrade to the boundary's panel, not to a blank document.
    renderPage('/faculty')

    // The boundary caught it, and named the page rather than saying "Error".
    await waitFor(
      () => expect(screen.getByRole('group', { name: /failed to render/i })).toBeInTheDocument(),
      { timeout: 5_000 },
    )
    expect(screen.getByText(/this page failed to render/i)).toBeInTheDocument()

    // And the chrome is still there to navigate away with.
    expect(screen.getByText('LecGap')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Student Portal/i })).toBeInTheDocument()
  })

  it('does not leave a blank page on an unknown route', async () => {
    renderPage('/nope')
    await waitFor(() => expect(screen.getByText('404')).toBeInTheDocument())
    // NotFound is inside the same boundary, and it must not be swallowed by it.
    expect(screen.getByText('LecGap')).toBeInTheDocument()
  })
})