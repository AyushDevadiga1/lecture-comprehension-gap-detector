import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CoursePicker } from './CoursePicker'
import { renderWithProviders } from '../../test/render'
import { mockFetch } from '../../test/fetchMock'
import type { MockRoute } from '../../test/fetchMock'
import { useAppStore } from '../../store/useAppStore'

/**
 * The course picker is the app's one owner of "which course is selected", and
 * it carries three behaviours that are easy to lose in a refactor: auto-select
 * when nothing is stored, fall back when the stored id has vanished, and refuse
 * to delete the last course. Each is a state the app can otherwise get stuck in.
 *
 * Moved here from Navbar verbatim; these tests exist so the move is checkable
 * rather than assumed.
 */

const twoCourses = [
  { course_id: 'ml', total_lectures: 3, ready_lectures: 3, total_concepts: 181, has_graph: true, node_count: 150, edge_count: 170 },
  { course_id: 'prob', total_lectures: 1, ready_lectures: 1, total_concepts: 51, has_graph: true, node_count: 46, edge_count: 73 },
]

const oneCourse = twoCourses.slice(0, 1)

function renderPicker(routes: MockRoute[] = [{ path: '/courses', json: twoCourses }]) {
  const mock = mockFetch(routes)
  const view = renderWithProviders(<CoursePicker />)
  return { mock, view }
}

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: null })
})

describe('CoursePicker', () => {
  it('renders the stored course as the selected value', async () => {
    useAppStore.setState({ selectedCourseId: 'ml' })
    renderPicker()
    expect(await screen.findByText('ML (3 lecs)')).toBeInTheDocument()
  })

  it('auto-selects the first course when nothing is stored', async () => {
    renderPicker()
    await waitFor(() => expect(useAppStore.getState().selectedCourseId).toBe('ml'))
  })

  it('falls back when the stored id no longer exists on the server', async () => {
    // A course deleted between sessions. Without the fallback every query would
    // fire against an id that 404s for the life of the tab.
    useAppStore.setState({ selectedCourseId: 'deleted-course' })
    renderPicker()
    await waitFor(() => expect(useAppStore.getState().selectedCourseId).toBe('ml'))
  })

  it('lists every course when opened', async () => {
    const user = userEvent.setup()
    useAppStore.setState({ selectedCourseId: 'ml' })
    renderPicker()

    await user.click(await screen.findByRole('combobox'))
    expect(await screen.findByRole('option', { name: 'ML (3 lecs)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'PROB (1 lec)' })).toBeInTheDocument()
  })

  it('refuses to delete the last remaining course', async () => {
    useAppStore.setState({ selectedCourseId: 'ml' })
    renderPicker([{ path: '/courses', json: oneCourse }])

    const del = await screen.findByRole('button', { name: 'Delete this course' })
    expect(del).toBeDisabled()
  })

  it('asks first, and names the course in the dialog', async () => {
    const user = userEvent.setup()
    useAppStore.setState({ selectedCourseId: 'ml' })
    renderPicker()

    await user.click(await screen.findByRole('button', { name: 'Delete this course' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Delete course ML\?/i)).toBeInTheDocument()
    // The blast radius is stated, not implied.
    expect(within(dialog).getByText(/Every lecture, concept, graph edge, clip/i)).toBeInTheDocument()
  })

  it('cancelling leaves everything alone', async () => {
    const user = userEvent.setup()
    useAppStore.setState({ selectedCourseId: 'ml' })
    const { mock } = renderPicker()

    await user.click(await screen.findByRole('button', { name: 'Delete this course' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(mock.callsTo('DELETE', '/courses/ml')).toHaveLength(0)
    expect(useAppStore.getState().selectedCourseId).toBe('ml')
  })

  it('confirming deletes the course and refetches the list', async () => {
    const user = userEvent.setup()
    useAppStore.setState({ selectedCourseId: 'ml' })
    const { mock } = renderPicker([
      { path: '/courses', json: twoCourses },
      { method: 'DELETE', path: '/courses/ml', json: { deleted: true, course_id: 'ml' } },
    ])

    await user.click(await screen.findByRole('button', { name: 'Delete this course' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Delete course' }))

    await waitFor(() => expect(mock.callsTo('DELETE', '/courses/ml')).toHaveLength(1))
    // Selection moves off the dead id before the invalidation refetches.
    expect(useAppStore.getState().selectedCourseId).toBe('prob')
    await waitFor(() => expect(mock.callsTo('GET', '/courses').length).toBeGreaterThan(1))
  })

  it('keeps the dialog open and shows the backend detail when deletion fails', async () => {
    const user = userEvent.setup()
    useAppStore.setState({ selectedCourseId: 'ml' })
    renderPicker([
      { path: '/courses', json: twoCourses },
      { method: 'DELETE', path: '/courses/ml', status: 500, json: { detail: 'database is locked' } },
    ])

    await user.click(await screen.findByRole('button', { name: 'Delete this course' }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: 'Delete course' }))

    expect(await screen.findByText('database is locked')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(useAppStore.getState().selectedCourseId).toBe('ml')
  })
})
