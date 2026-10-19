import { beforeEach, describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import type { FeedState } from '../../../lib/jobFeed'
import { QueryClient } from '@tanstack/react-query'
import type { LectureDetailOut } from '../../../api/types'
import { queryKeys } from '../../../lib/queryKeys'
import { renderWithProviders } from '../../../test/render'
import { mockFetch } from '../../../test/fetchMock'
import { useAppStore } from '../../../store/useAppStore'
import { LectureDetailView } from './LectureDetailView'

/**
 * The lecture detail view wires the coverage timeline (P2.2) onto the
 * lecture picker (P0) and adds the live progress card (P2.3).
 */

const list = () =>
  [
    {
      id: 1,
      course_id: 'ml',
      title: 'Linear Regression',
      status: 'ready',
      error: null,
      created_at: '2026-01-01T00:00:00Z',
      processed_at: null,
      has_media: true,
      job_id: null,
    },
  ] as const

const detail: LectureDetailOut = {
  id: 1,
  course_id: 'ml',
  title: 'Linear Regression',
  status: 'ready',
  error: null,
  created_at: '2026-01-01T00:00:00Z',
  processed_at: null,
  has_media: true,
  job_id: null,
  segments: [
    { idx: 0, start_s: 0, end_s: 6, text: 'A linear regression fits a straight line.' },
    { idx: 1, start_s: 6, end_s: 12, text: 'The slope is the coefficient on x.' },
  ],
  concepts: [
    { id: 1, name: 'Linear Regression', source: 'spoken', implicit: false, start_s: 0, end_s: 6 },
    { id: 2, name: 'Slope', source: 'spoken', implicit: false, start_s: 6, end_s: 12 },
  ],
}

function renderLectureDetail(
  routes: { list?: unknown; detail?: unknown; progress?: unknown },
  queryClientOverride?: QueryClient,
) {
  const mock = mockFetch([
    { path: '/lectures', json: routes.list ?? list() },
    { path: '/lectures/1', json: routes.detail ?? detail },
    ...(routes.progress ? [{ path: '/lectures/1/progress', json: routes.progress }] : []),
  ])
  const view = renderWithProviders(<LectureDetailView />, {
    route: '/student/lecture',
    queryClient: queryClientOverride,
  })
  return { mock, view, queryClient: view.queryClient as QueryClient }
}

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: 'ml' })
})

describe('LectureDetailView', () => {
  it('renders the picker and the coverage timeline for a ready lecture', async () => {
    const result = renderLectureDetail({})
  void result.mock

    await screen.findByRole('img', { name: 'Lecture coverage timeline' })
    // The honest percentage: the seeded lecture is covered wall to wall.
    expect(screen.getByText('100% of the lecture covered')).toBeInTheDocument()
    await expect(
      screen.getByRole('cell', { name: '0.0 – 6.0s' }),
    ).toBeInTheDocument()
    await expect(
      screen.getByRole('cell', { name: '6.0 – 12.0s' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('cell', {
        name: 'A linear regression fits a straight line.',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'The slope is the coefficient on x.' })).toBeInTheDocument()
  })

  it('shows live job progress when a job is visible for the lecture', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(queryKeys.jobs('ml'), {
      jobs: [
        {
          id: 7,
          kind: 'transcribe',
          status: 'running',
          course_id: 'ml',
          lecture_id: 1,
          title: 'Linear Regression',
          stage: 'decoding',
          progress_pct: 55,
          detail: null,
          error: null,
          terminal: false,
        },
      ],
      mode: 'live',
      changeToken: 1,
    } as unknown as FeedState)

  const result = renderLectureDetail(
    {
      list: [{ ...list()[0], status: 'transcribing' }],
      detail: { ...detail, status: 'transcribing' },
    },
    queryClient,
  )
  void result.mock

    await screen.findByText('decoding · 55%')
    expect(screen.getByText('Live from the job feed (transcribe).')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: 'Lecture coverage timeline' })).not.toBeInTheDocument()
  })
    it('polls /progress when nothing in the feed covers the lecture', async () => {
      const queryClient = new QueryClient()
      queryClient.setQueryData(queryKeys.jobs('ml'), {
        jobs: [],
        mode: 'live',
        changeToken: 1,
    } as unknown as FeedState)

  const result = renderLectureDetail(
    {
      list: [{ ...list()[0], status: 'transcribing' }],
      detail: { ...detail, status: 'transcribing' },
      progress: {
        lecture_id: 1,
        status: 'transcribing',
        stage: 'decoding',
        progress_pct: 40,
        elapsed_s: 7,
      },
    },
    queryClient,
  )
  void result.mock

      await screen.findByText('decoding · 40%')
      expect(screen.queryByRole('img', { name: 'Lecture coverage timeline' })).not.toBeInTheDocument()
    })
  })