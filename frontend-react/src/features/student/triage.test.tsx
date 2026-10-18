import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LecturesView } from './views/LecturesView'
import { renderWithProviders } from '../../test/render'
import { mockFetch } from '../../test/fetchMock'
import type { FetchMock } from '../../test/fetchMock'
import { useAppStore } from '../../store/useAppStore'

/**
 * The triage contract, proved where it can break: at the call site.
 *
 * `lib/lectureTriage.test.ts` proves the split (resumable vs abandoned) and
 * the duplicate match. It cannot prove the dashboard *acts* on them — that
 * the warning gates the submit, that Start processing POSTs a rerun, that
 * Delete empty rows DELETEs. A wrong wire here fails silently (the button
 * does nothing, or the wrong endpoint fires), exactly like the quiz-cap bug
 * `quizWiring.test.tsx` exists for.
 *
 * Each test carries a 30 s timeout, stated plainly: the dashboard lazy-loads
 * the DAG view, and transforming reactflow cold (first run, fresh CI cache)
 * takes seconds before any assertion runs. That cost is the lazy boundary
 * doing its production job, not a slow test.
 */

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: 'ml' })
})

const lectures = [
  // Mirrors the backend contract: GET /lectures?course_id=ml returns ml rows
  // only (the dashboard passes course_id; it does not filter client-side).
  // Cross-course filtering lives one layer down and is pinned there —
  // splitStalled and findDuplicate both take a courseId and both are tested
  // against other-course rows in lib/lectureTriage.test.ts.
  { id: 1, course_id: 'ml', title: 'Linear Regression', status: 'ready', created_at: '2026-01-01', has_media: true },
  { id: 2, course_id: 'ml', title: 'Half Upload', status: 'uploaded', created_at: '2026-01-02', has_media: true },
  { id: 3, course_id: 'ml', title: 'Dead Row', status: 'uploaded', created_at: '2026-01-03', has_media: false },
]

const snapshot = {
  exists: true,
  course_id: 'ml',
  lectures: { total: 3, ready: 1, uploaded: 2, transcribing: 0, error: 0 },
  concepts: 0,
  graph: { has: false, nodes: 0, edges: 0 },
  clips: { cut: 0, ok: 0 },
  quiz: { questions: 0, respondents: 0 },
  in_flight: [],
}

const emptyGraph = {
  course_id: 'ml',
  nodes: [],
  edges: [],
  node_count: 0,
  edge_count: 0,
  is_dag: true,
  topological_order: [],
}

function routes(extra: Parameters<typeof mockFetch>[0] = []) {
  return [
    { path: '/courses/ml/snapshot', json: snapshot },
    { path: '/lectures', json: lectures },
    { path: '/courses/ml/graph', json: emptyGraph },
    { path: /^\/lectures\/\d+\/clips$/, json: { lecture_id: 0, status: 'ok', clips: [] } },
    ...extra,
  ]
}

async function renderDashboard(extraRoutes: Parameters<typeof mockFetch>[0] = []) {
  const mock = mockFetch(routes(extraRoutes))
  renderWithProviders(<LecturesView />)
  // Lectures table proves the rows (and therefore the triage inputs) loaded.
  await screen.findByText('Half Upload')
  return mock
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]')
  if (!(input instanceof HTMLInputElement)) throw new Error('no file input rendered')
  return input
}

describe('duplicate guard', () => {
  it('warns and blocks submit until the duplicate is acknowledged', async () => {
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByLabelText(/Lecture Title/i), 'linear regression')
    await user.upload(fileInput(), new File(['x'], 'linear regression.mp4', { type: 'video/mp4' }))

    // Names lecture #1 — scoped to the warning alert, because #1 also
    // appears in the lectures table below and sibling alerts (quiz info)
    // share the role. A bare query matches all of them.
    expect(await screen.findByText(/already looks like this file/)).toBeInTheDocument()
    const alerts = await screen.findAllByRole('alert')
    const warning = alerts.find(
      (a) => within(a).queryByText(/already looks like this file/) != null,
    )
    expect(warning).toBeTruthy()
    expect(within(warning!).getByText(/#1/)).toBeInTheDocument()
    const submit = screen.getByRole('button', { name: /Upload & Transcribe/ })
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('checkbox', { name: /Upload anyway/ }))
    expect(submit).toBeEnabled()
  }, 30000)

  it('stays out of the way for a fresh filename', async () => {
    const user = userEvent.setup()
    await renderDashboard()

    await user.type(screen.getByLabelText(/Lecture Title/i), 'Brand New')
    await user.upload(fileInput(), new File(['x'], 'brand new.mp4', { type: 'video/mp4' }))

    expect(screen.queryByText(/already looks like this file/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Upload & Transcribe/ })).toBeEnabled()
  }, 30000)
})

describe('stalled rows', () => {
  it('splits resumable from abandoned with opposite actions', async () => {
    await renderDashboard()

    expect(await screen.findByText(/never started/)).toBeInTheDocument()
    expect(screen.getByText('Half Upload')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Start processing' }),
    ).toBeInTheDocument()

    expect(screen.getByText(/no file arrived/)).toBeInTheDocument()
    expect(screen.getByText(/Delete these empty rows/)).toBeInTheDocument()
  }, 30000)

  it('Start processing POSTs a rerun for that lecture', async () => {
    const user = userEvent.setup()
    const mock: FetchMock = await renderDashboard([
      { method: 'POST', path: '/lectures/2/rerun', json: { id: 2 } },
    ])

    await user.click(await screen.findByRole('button', { name: 'Start processing' }))

    await waitFor(() => {
      expect(mock.callsTo('POST', '/lectures/2/rerun')).toHaveLength(1)
    })
  }, 30000)

  it('bulk delete confirms, then DELETEs each abandoned row', async () => {
    const user = userEvent.setup()
    const mock: FetchMock = await renderDashboard([
      { method: 'DELETE', path: '/lectures/3', json: { deleted: true } },
    ])

    await user.click(await screen.findByText(/Delete these empty rows/))
    // Confirmation names the stakes, mirroring the session-removal dialog.
    expect(await screen.findByText(/Delete empty rows\?/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Delete empty rows' }))

    await waitFor(() => {
      expect(mock.callsTo('DELETE', '/lectures/3')).toHaveLength(1)
    })
  }, 30000)
})
