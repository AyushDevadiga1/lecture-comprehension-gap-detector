import { beforeEach, describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { OverviewView } from './OverviewView'
import { renderWithProviders } from '../../../test/render'
import { mockFetch } from '../../../test/fetchMock'
import { useAppStore } from '../../../store/useAppStore'

/**
 * Overview is the only view with a next-actions card and an in-flight card, and
 * both are easy to get silently wrong: the first can link to a route that does
 * not exist, the second can render a spinner for a row that needs triage.
 *
 * The quota card is asserted here as well as in `SystemView`, because both read
 * the same `['usage']` key through the same formatter — if they disagree, one
 * of them is lying.
 */

const snapshot = (inFlight: unknown[] = []) => ({
  exists: true,
  course_id: 'ml',
  lectures: { total: 3, ready: 2, uploaded: 1, transcribing: 0, error: 0 },
  concepts: 181,
  graph: { has: true, nodes: 150, edges: 170 },
  clips: { cut: 52, ok: 37 },
  quiz: { questions: 89, respondents: 1 },
  in_flight: inFlight,
})

const usage = {
  services: {
    'groq.chat': { remaining_requests: 4812, reset_in_s: 720 },
    'groq.whisper': { remaining_requests: 71 },
    local: { available: true, ffmpeg_ok: true },
  },
}

function renderOverview(opts: { inFlight?: unknown[]; usage?: unknown } = {}) {
  const mock = mockFetch([
    { path: '/courses/ml/snapshot', json: snapshot(opts.inFlight) },
    { path: '/usage', json: opts.usage ?? usage },
  ])
  const view = renderWithProviders(<OverviewView />, { route: '/student/overview' })
  return { mock, view }
}

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: 'ml' })
})

describe('OverviewView', () => {
  it('renders the snapshot strip from the payload', async () => {
    renderOverview()
    expect(await screen.findByText('3 (2 ready)')).toBeInTheDocument()
    expect(screen.getByText('181')).toBeInTheDocument()
    expect(screen.getByText('170 edges')).toBeInTheDocument()
    expect(screen.getByText('37 / 52 OK')).toBeInTheDocument()
    // The uploaded count is stated, because triage is about that number.
    expect(screen.getByText(/1 uploaded · 0 transcribing · 0 error/)).toBeInTheDocument()
  })

  it('says nothing is processing rather than showing an empty spinner', async () => {
    renderOverview()
    expect(await screen.findByText(/Nothing is processing right now/)).toBeInTheDocument()
  })

  it('shows each in-flight lecture with its stage and progress', async () => {
    renderOverview({
      inFlight: [
        {
          lecture_id: 2,
          title: 'Gated Recurrent Unit (GRU)',
          status: 'transcribing',
          stage: 'extracting',
          progress_pct: 70,
        },
      ],
    })

    expect(await screen.findByText('#2 — Gated Recurrent Unit (GRU)')).toBeInTheDocument()
    expect(screen.getByText('extracting · 70%')).toBeInTheDocument()
  })

  it('renders the quota rows from the shared usage payload', async () => {
    renderOverview()
    expect(await screen.findByText('Groq chat')).toBeInTheDocument()
    expect(screen.getByText('4,812 requests left · resets in 12m')).toBeInTheDocument()
    expect(screen.getByText('Groq whisper')).toBeInTheDocument()
    expect(screen.getByText('Local Whisper')).toBeInTheDocument()
  })

  it('offers working next actions, one per destination that exists', async () => {
    renderOverview()
    const card = (await screen.findByText('Where to go next')).closest('.MuiCardContent-root')
    expect(card).not.toBeNull()
    const next = card as HTMLElement

    for (const [label, href] of [
      ['Upload a lecture', '/student/lectures'],
      ['Open the concept map', '/student/map'],
      ['Take the quiz', '/student/quiz'],
      ['Study the plan', '/student/remediation'],
    ] as const) {
      expect(within(next).getByRole('link', { name: new RegExp(label) })).toHaveAttribute(
        'href',
        href,
      )
    }
  })

  it('reports a snapshot failure instead of an empty page', async () => {
    mockFetch([{ path: '/courses/ml/snapshot', status: 500, json: { detail: 'boom' } }])
    renderWithProviders(<OverviewView />, { route: '/student/overview' })
    expect(await screen.findByText('boom')).toBeInTheDocument()
  })

  it('survives a usage failure quietly — it is ambient, not an error banner', async () => {
    mockFetch([
      { path: '/courses/ml/snapshot', json: snapshot() },
      { path: '/usage', status: 500, json: { detail: 'no usage for you' } },
    ])
    renderWithProviders(<OverviewView />, { route: '/student/overview' })

    expect(await screen.findByText('3 (2 ready)')).toBeInTheDocument()
    expect(screen.queryByText('no usage for you')).not.toBeInTheDocument()
  })
})
