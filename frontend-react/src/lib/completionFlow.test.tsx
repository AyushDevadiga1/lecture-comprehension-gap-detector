import { describe, expect, it } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useActiveJobs, useJobList } from './useJobFeed'
import { recordNewCompletions } from './jobCompletions'
import { useCompletionStore } from '../store/useCompletionStore'
import { queryKeys } from './queryKeys'
import { JobCompletionHost } from '../components/common/JobCompletionHost'
import { renderWithProviders } from '../test/render'
import type { JobOut } from '../api/types'

/**
 * §1: a terminal job leaves the live view after one render, and its completion
 * is announced once by the page body — never from inside the progress surface.
 *
 * The Python twin is `shell.py:586-620` (`_record_ready` / `drain_ready`).
 * The "once" half is covered as a pure function in `jobCompletions.test.ts`;
 * this file covers the two halves a component can get wrong: the live view
 * actually drops the job, and the announcement is actually shown and dismissed.
 */

const job = (over: Partial<JobOut> = {}): JobOut => {
  // Timestamps must be recent: a job with no heartbeat older than the six-hour
  // backstop is (correctly) dropped from the live view.
  const now = new Date().toISOString()
  return {
    id: 1,
    kind: 'transcribe',
    status: 'running',
    course_id: 'ML',
    lecture_id: 1,
    title: 'Lecture',
    stage: 'transcribing',
    detail: 'working',
    progress_pct: 40,
    created_at: now,
    started_at: now,
    heartbeat_at: now,
    terminal: false,
    ...over,
  } as JobOut
}

function LiveViews() {
  const active = useActiveJobs('ML')
  const all = useJobList('ML')
  return (
    <>
      <div data-testid="live">{active.length}</div>
      <div data-testid="all">{all.length}</div>
    </>
  )
}

describe('the live view drops a finished job', () => {
  it('separates active from total', async () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <LiveViews />
      </QueryClientProvider>,
    )

    const emit = (jobs: JobOut[], token: number) =>
      act(() => {
        queryClient.setQueryData(queryKeys.jobs('ML'), { jobs, mode: 'stream', changeToken: token })
      })

    emit([job()], 1)
    await waitFor(() => expect(screen.getByTestId('live').textContent).toBe('1'))
    expect(screen.getByTestId('all').textContent).toBe('1')

    emit([job({ status: 'ready', terminal: true, progress_pct: 100 })], 2)
    await waitFor(() => expect(screen.getByTestId('live').textContent).toBe('0'))
    // The row still exists server-side; it is simply no longer "live".
    expect(screen.getByTestId('all').textContent).toBe('1')
  })

  it('drops a job by status word even without the terminal flag', async () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <LiveViews />
      </QueryClientProvider>,
    )
    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), {
        jobs: [job({ status: 'orphaned', terminal: false })],
        mode: 'stream',
        changeToken: 1,
      })
    })
    await waitFor(() => expect(screen.getByTestId('live').textContent).toBe('0'))
  })
})

describe('recordNewCompletions drives the queue', () => {
  it('pushes once, however many times the feed repeats the snapshot', () => {
    const pushed: number[] = []
    let prev: JobOut[] = [job()]
    const record = (jobs: JobOut[]) => {
      recordNewCompletions(prev, jobs, (list) => pushed.push(...list.map((a) => a.jobId)))
      prev = jobs
    }

    for (let i = 1; i <= 3; i++) record([job({ progress_pct: i * 10 })])
    expect(pushed).toEqual([])

    const done = [job({ status: 'ready', terminal: true, progress_pct: 100 })]
    record(done)
    // The feed keeps re-sending the terminal row; the queue is not re-pushed.
    for (let i = 0; i < 5; i++) record(done)

    expect(pushed).toEqual([1])
  })
})

describe('the announcement is shown in the page body', () => {
  it('renders the completion detail and can be dismissed', async () => {
    useCompletionStore.getState().clear()
    useCompletionStore.getState().push([
      {
        jobId: 7,
        lectureId: 3,
        courseId: 'ML',
        title: 'Cut clips',
        kind: 'clips',
        status: 'ready',
        detail: 'Clips cut for lecture 3',
        error: null,
        after: 'clips_list',
        wasStopped: false,
      },
    ])

    renderWithProviders(<JobCompletionHost />)
    await waitFor(() => expect(screen.getByText(/Clips cut for lecture 3/)).toBeInTheDocument())

    act(() => useCompletionStore.getState().dismiss('job-7'))
    await waitFor(() => expect(screen.queryByText(/Clips cut for lecture 3/)).not.toBeInTheDocument())
  })

  it('does not re-announce a stale queue left over from a previous session', async () => {
    useCompletionStore.getState().clear()
    useCompletionStore.getState().push([
      {
        jobId: 99,
        lectureId: 1,
        courseId: 'ML',
        title: 'Old job',
        kind: 'transcribe',
        // 10 minutes old, past the staleness window.
        status: 'ready',
        detail: 'done long ago',
        error: null,
        after: null,
        wasStopped: false,
      },
    ])
    const stale = useCompletionStore.getState().items[0]!
    useCompletionStore.setState({ items: [{ ...stale, at: Date.now() - 10 * 60_000 }] })

    renderWithProviders(<JobCompletionHost />)
    await waitFor(() => expect(screen.queryByText(/done long ago/)).not.toBeInTheDocument())
  })
})
