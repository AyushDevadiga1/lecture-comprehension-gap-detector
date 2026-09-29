import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { Button } from '@mui/material'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useBusyLectureIds } from './useJobFeed'
import { queryKeys } from './queryKeys'
import type { JobOut } from '../api/types'

/**
 * The C0 rule: "Disable a job's buttons while it is in flight" so work cannot
 * be double-fired. The Streamlit engine does this with
 * `busy = shell.active_job(lecture_id)` (`panels/ingest.py:103-106`); the React
 * row buttons were never disabled, so a double-click queued duplicate work.
 */

const nowIso = () => new Date().toISOString()

/** Timestamps must be recent: a job whose heartbeat is past the six-hour
 * backstop is (correctly) dropped from the live view. */
const job = (over: Partial<JobOut> = {}): JobOut =>
  ({
    id: 1,
    kind: 'extract',
    status: 'running',
    course_id: 'ML',
    lecture_id: 1,
    title: 'Lecture',
    stage: 'extracting',
    detail: 'working',
    progress_pct: 40,
    created_at: nowIso(),
    started_at: nowIso(),
    heartbeat_at: nowIso(),
    terminal: false,
    ...over,
  }) as JobOut

/** A row of action buttons, wired the way StudentDashboard wires them. */
function Row({ onFire, lectureId }: { onFire: (id: number) => void; lectureId: number }) {
  const busy = useBusyLectureIds('ML').has(lectureId)
  return (
    <Button disabled={busy} onClick={() => onFire(lectureId)}>
      Extract Concepts
    </Button>
  )
}

const button = () => screen.getByRole('button', { name: 'Extract Concepts' })

describe('a busy lecture disables its actions', () => {
  it('is disabled while a job is in flight for that lecture', async () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <Row onFire={vi.fn()} lectureId={1} />
      </QueryClientProvider>,
    )
    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), {
        jobs: [job()],
        mode: 'stream',
        changeToken: 1,
      })
    })
    await waitFor(() => expect(button()).toBeDisabled())
  })

  it('is enabled when no job is in flight', async () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <Row onFire={vi.fn()} lectureId={1} />
      </QueryClientProvider>,
    )
    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), { jobs: [], mode: 'stream', changeToken: 1 })
    })
    await waitFor(() => expect(button()).toBeEnabled())
  })

  it('is enabled again once the job reaches a terminal state', async () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <Row onFire={vi.fn()} lectureId={1} />
      </QueryClientProvider>,
    )
    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), {
        jobs: [job()],
        mode: 'stream',
        changeToken: 1,
      })
    })
    await waitFor(() => expect(button()).toBeDisabled())

    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), {
        jobs: [job({ status: 'ready', terminal: true })],
        mode: 'stream',
        changeToken: 2,
      })
    })
    await waitFor(() => expect(button()).toBeEnabled())
  })

  it('a job for a different lecture does not disable this one', async () => {
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <Row onFire={vi.fn()} lectureId={1} />
      </QueryClientProvider>,
    )
    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), {
        jobs: [job({ id: 9, lecture_id: 2 })],
        mode: 'stream',
        changeToken: 1,
      })
    })
    await waitFor(() => expect(button()).toBeEnabled())
  })

  it('a double-click cannot queue the work twice', async () => {
    const onFire = vi.fn()
    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <Row onFire={onFire} lectureId={1} />
      </QueryClientProvider>,
    )
    act(() => {
      queryClient.setQueryData(queryKeys.jobs('ML'), {
        jobs: [job()],
        mode: 'stream',
        changeToken: 1,
      })
    })
    await waitFor(() => expect(button()).toBeDisabled())

    // MUI renders a real <button disabled>, and a disabled button ignores
    // click() outright. That is the property the C0 rule relies on, so the raw
    // DOM click is the honest assertion -- userEvent cannot be used here because
    // it throws on `pointer-events: none` instead of proving the swallow.
    button().click()
    button().click()
    expect(onFire).not.toHaveBeenCalled()
  })
})
