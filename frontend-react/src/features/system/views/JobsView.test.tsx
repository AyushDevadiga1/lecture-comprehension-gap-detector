import { beforeEach, describe, expect, it } from 'vitest'
import { act, screen } from '@testing-library/react'
import { JobsView } from './JobsView'
import { renderWithProviders } from '../../../test/render'
import { queryKeys } from '../../../lib/queryKeys'
import { useAppStore } from '../../../store/useAppStore'
import type { FeedState } from '../../../lib/jobFeed'
import type { JobOut } from '../../../api/types'

/**
 * JobsView reads the feed cache, never `/jobs` — so the test seeds
 * `['jobs', 'ml']` directly, exactly as the SSE sink does, and asserts the
 * summary strip and the elapsed column the registry view adds.
 */

const job = (over: Partial<JobOut> = {}): JobOut =>
  ({
    id: 1,
    kind: 'transcribe',
    status: 'running',
    course_id: 'ML',
    lecture_id: 1,
    title: 'Lecture 1',
    stage: 'transcribing',
    detail: null,
    progress_pct: 40,
    error: null,
    created_at: '2026-10-19T20:00:00Z',
    started_at: '2026-10-19T20:00:05Z',
    finished_at: null,
    heartbeat_at: '2026-10-19T20:00:10Z',
    duration_s: null,
    terminal: false,
    ...over,
  }) as JobOut

const seed = (jobs: JobOut[], changeToken = 1): FeedState => ({
  jobs,
  mode: 'stream',
  changeToken,
})

/** Render the view with the job cache already seeded, as the feed would have left it. */
function renderJobs(jobs: JobOut[] = []) {
  const queryClient = renderWithProviders(<JobsView />, { route: '/jobs' }).queryClient
  act(() => {
    queryClient.setQueryData(queryKeys.jobs('ml'), seed(jobs))
  })
  return queryClient
}

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: 'ml' })
})

describe('JobsView', () => {
  it('summarises running, finished and orphaned jobs', () => {
    renderJobs([
      job({ id: 1, status: 'running', terminal: false }),
      job({ id: 2, status: 'ready', terminal: true, finished_at: '2026-10-19T20:01:00Z' }),
      job({ id: 3, status: 'orphaned', terminal: true }),
    ])

    expect(screen.getByText('Running now')).toBeInTheDocument()
    expect(screen.getByText('Finished')).toBeInTheDocument()
    // The strip label and the note's bold lead-in both read "Orphaned".
    expect(screen.getAllByText('Orphaned').length).toBeGreaterThan(0)
    expect(screen.getByText('Snapshot token')).toBeInTheDocument()
    expect(screen.getAllByText('#1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('#2').length).toBeGreaterThan(0)
    expect(screen.getAllByText('#3').length).toBeGreaterThan(0)
  })

  it('shows an elapsed value for each row', () => {
    renderJobs([
      job({
        id: 2,
        status: 'ready',
        terminal: true,
        started_at: '2026-10-19T20:00:00Z',
        finished_at: '2026-10-19T20:04:12Z',
      }),
    ])

    // 4m 12s — the mock's own example, so the column reads the way the mock does.
    expect(screen.getByText('4m 12s')).toBeInTheDocument()
  })

  it('explains what an orphaned job is when one exists', () => {
    renderJobs([job({ id: 3, status: 'orphaned', terminal: true })])

    expect(screen.getByText(/server restarted while the job was running/)).toBeInTheDocument()
  })

  it('says there are no jobs rather than rendering an empty table', () => {
    renderJobs([])

    expect(screen.getByText(/No background jobs for this course yet/)).toBeInTheDocument()
  })
})
