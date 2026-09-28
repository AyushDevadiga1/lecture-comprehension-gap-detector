import { describe, expect, it } from 'vitest'
import { useState } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { useJobList } from './useJobFeed'
import { queryKeys } from './queryKeys'
import { createTestQueryClient } from '../test/queries'
import { renderWithProviders } from '../test/render'
import appLayoutSource from '../components/layout/AppLayout.tsx?raw'
import type { JobOut } from '../api/types'

/**
 * The §10 gate, built early so it guards the rest of the campaign:
 *
 *   "a Playwright test that a job running for 30s does **not** restart a playing
 *    <video>"
 *
 * and §0's rule: *a value that changes must never be the reason a component
 * re-renders*.
 *
 * The old wiring had AppLayout subscribe to the job store, and AppLayout renders
 * <Outlet/>. React reconciles a remounted <video> by reloading its source, so a
 * 1Hz progress tick was enough to restart playback — the exact Streamlit defect
 * the rebuild exists to remove.
 */


const job = (over: Partial<JobOut> = {}): JobOut =>
  ({
    id: 1,
    kind: 'transcribe',
    status: 'running',
    course_id: 'ML',
    lecture_id: 1,
    title: 'Lecture',
    stage: 'transcribing',
    detail: 'working',
    progress_pct: 40,
    created_at: '2026-09-28T00:00:00Z',
    terminal: false,
    ...over,
  }) as JobOut

let pageRenders = 0
let drawerRenders = 0

/** Stands in for a dashboard page: owns a <video>, counts its own renders. */
function Page() {
  pageRenders += 1
  const [playing] = useState(true)
  return (
    <div>
      <video data-testid="player" src="/media/clips/1/a.mp4" autoPlay={playing} controls />
      <p>page body</p>
    </div>
  )
}

/** Stands in for JobDrawer: the one place job progress is displayed. */
function Drawer() {
  const jobs = useJobList('ML')
  drawerRenders += 1
  return <div data-testid="drawer">{jobs.length} job(s)</div>
}

describe('a job tick does not re-render the page', () => {
  it('leaves a page containing a <video> untouched while the drawer updates', async () => {
    pageRenders = 0
    drawerRenders = 0
    const queryClient = createTestQueryClient()

    // Same shape the real app has: a page and a drawer over one query client.
    render(
      <QueryClientProvider client={queryClient}>
        <Page />
        <Drawer />
      </QueryClientProvider>,
    )

    // Exactly what the sink does on an SSE snapshot. Deliberately not going
    // through jobFeed: the transport has its own suite, and connecting here
    // would publish its own empty snapshot over the data under test.
    const emit = (changeToken: number, jobs: JobOut[]) =>
      act(() => {
        queryClient.setQueryData(queryKeys.jobs('ML'), { jobs, mode: 'stream', changeToken })
      })

    emit(1, [job({ progress_pct: 10 })])
    await waitFor(() => expect(screen.getByTestId('drawer').textContent).toBe('1 job(s)'))

    const pageAfterFirstTick = pageRenders
    // The drawer -- the component that displays progress -- did re-render.
    expect(drawerRenders).toBeGreaterThan(0)
    // The page did not. This is the assertion the rebuild exists for.
    expect(pageRenders).toBe(1)

    emit(2, [job({ progress_pct: 20 })])
    emit(3, [job({ progress_pct: 30 })])
    await waitFor(() => expect(drawerRenders).toBeGreaterThan(1))

    expect(pageRenders).toBe(pageAfterFirstTick)
  })

  it('still re-renders the page for a reason unrelated to jobs', () => {
    // Guards against the case above passing for the wrong reason: if Page never
    // re-rendered under any circumstance, the first case would be vacuous.
    pageRenders = 0
    const queryClient = createTestQueryClient()
    const { rerender } = renderWithProviders(<Page />, { queryClient })
    const before = pageRenders
    rerender(<Page />)
    expect(pageRenders).toBe(before + 1)
  })
})

describe('§1 — the feed is read only where progress is shown', () => {
  it('AppLayout connects the feed without reading job state', () => {
    // AppLayout renders <Outlet/>. If it reads the jobs cache, every tick
    // re-renders the whole routed page. A static guard so the rule survives a
    // future refactor — the Python twin is tests/test_theme.py's colour scanner.
    expect(appLayoutSource).toContain('useJobFeedConnection')
    for (const hook of ['useJobs(', 'useJobList(', 'useActiveJobs(', 'useJobCards(', 'useFeedStatus(']) {
      expect(appLayoutSource, `AppLayout must not call ${hook}`).not.toContain(hook)
    }
    expect(appLayoutSource).not.toContain('useJobStore')
  })

  it('no component reaches for the feed singleton', () => {
    const sources = import.meta.glob('../components/**/*.{ts,tsx}', {
      query: '?raw',
      import: 'default',
      eager: true,
    }) as Record<string, string>

    const files = Object.keys(sources)
    expect(files.length).toBeGreaterThan(0)
    for (const [file, src] of Object.entries(sources)) {
      expect(src, `${file} must not touch the feed singleton`).not.toContain('jobFeed.')
    }
  })
})
