/**
 * *Start Quiz* must send the cap. This is the seam the api test cannot reach.
 *
 * ## Why this file is separate from `api/quizzes.test.ts`
 *
 * `api/quizzes.test.ts` proves the transport: given a number, the field is in
 * the body. It cannot prove the caller supplies one — and the caller is where
 * this actually broke. `StudentDashboard.tsx` computed `const cap =
 * quizMaxQuestions()` and once passed it as `createJob(courseId, studentId)`.
 * Every test in the repo stayed green, because nothing ever asked what the
 * button put on the wire, and `POST /quizzes` generates one LLM call per
 * concept against a 153-concept course.
 *
 * Verified: with `cap` deleted from the call, the 14 `lib/quiz` unit tests and
 * the 7 `api/quizzes` tests all still pass. Only this one goes red.
 *
 * ## Why the dashboard and not the mutation
 *
 * The mutation body is three lines and its inputs are the interesting part. The
 * whole dashboard is rendered rather than the mutation extracted, because
 * "the component calls `createJob` with the cap" is the claim, and extracting
 * the mutation to test it would let the caller change without the test
 * noticing — which is the failure being guarded against.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { StudentDashboard } from './StudentDashboard'
import { renderWithProviders } from '../../test/render'
import { mockFetch } from '../../test/fetchMock'
import { createTestQueryClient } from '../../test/queries'
import { queryKeys } from '../../lib/queryKeys'
import { useAppStore } from '../../store/useAppStore'
import { quizMaxQuestions } from '../../lib/quiz'

beforeEach(() => {
  useAppStore.setState({ selectedCourseId: 'ml' })
})

/** The routes the dashboard needs to reach the Start Quiz button. */
function dashboardRoutes() {
  return [
    {
      path: '/courses/ml/snapshot',
      json: {
        course_id: 'ml',
        lectures: { total: 0, ready: 0 },
        concepts: 0,
        graph: { has: false, nodes: 0, edges: 0 },
        clips: { cut: 0, ok: 0 },
      },
    },
    { path: '/lectures', json: [] },
  ]
}

/** A quiz payload with `n` questions, shaped as `QuizOut`. */
function manyQuestions(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    concept: `c${i}`,
    question: 'q',
    options: ['a', 'b'],
    correct_index: 0,
  }))
}

async function renderDashboard() {
  const mock = mockFetch(dashboardRoutes())
  const view = renderWithProviders(<StudentDashboard />)
  // The button only renders once the course is set, which it is from the store.
  await screen.findByRole('button', { name: /Start Quiz/i })
  return { mock, view }
}

describe('the Start Quiz button', () => {
  it('puts the computed cap in the request body', async () => {
    const { mock, view } = await renderDashboard()

    await view.user.click(screen.getByRole('button', { name: /Start Quiz/i }))

    await waitFor(() => expect(mock.callsTo('POST', '/quizzes/jobs')).toHaveLength(1))
    expect(mock.callsTo('POST', '/quizzes/jobs')[0]!.body).toMatchObject({
      course_id: 'ml',
      max_questions: quizMaxQuestions(),
    })
  })

  it('queues a job rather than blocking on the synchronous endpoint', async () => {
    // The synchronous POST /quizzes is the one that froze the page for minutes;
    // `plan/FRONTEND_API_CONTRACT.md` §2 says no UI may call it. Asserted
    // because the fix was "use the job endpoint", and a regression to the
    // blocking one would be invisible otherwise — it still produces questions,
    // just minutes later.
    const { mock, view } = await renderDashboard()

    await view.user.click(screen.getByRole('button', { name: /Start Quiz/i }))

    await waitFor(() => expect(mock.callsTo('POST', '/quizzes/jobs')).toHaveLength(1))
    expect(mock.callsTo('POST', '/quizzes')).toHaveLength(0)
  })

  it('tells the user the cap before they press it', async () => {
    // "Up to 15 questions, drawn evenly from across the course's concepts." The
    // cap is a promise made on screen; if the number shown and the number sent
    // ever diverge, the UI is lying. Both sides come from `quizMaxQuestions()`,
    // which is what makes them agree — this pins that they are asked of the
    // same source rather than being restated.
    await renderDashboard()

    await waitFor(() => {
      expect(screen.getByText(/Up to \d+ questions/)).toHaveTextContent(
        `Up to ${quizMaxQuestions()} questions`,
      )
    })
  })

  it('warns when the backend returns more questions than were asked for', async () => {
    // `capViolation` is unit-tested as a pure string function; this proves the
    // UI actually reaches it, which needs a quiz response that over-delivers.
    // The numbers are the handoff's own signature: a course with 153 concepts
    // returning 153 questions means the cap did not apply server-side.
    const queryClient = createTestQueryClient()
    const view = renderWithProviders(<StudentDashboard />, { queryClient })
    const mock = mockFetch([
      ...dashboardRoutes(),
      { method: 'POST', path: '/quizzes/jobs', status: 202, json: { job_id: 77, status: 'queued' } },
      { path: '/quizzes', json: { course_id: 'ml', student_id: 'alice', questions: manyQuestions(153) } },
    ])
    await screen.findByRole('button', { name: /Start Quiz/i })

    // Step 1: press the button, which records job id 77 in a ref. Waited on the
    // request rather than the "Queueing..." copy — that label is bound to the
    // mutation's isPending and disappears as soon as the POST resolves, so it is
    // a race, not a synchronisation point.
    await view.user.click(screen.getByRole('button', { name: /Start Quiz/i }))
    await waitFor(() => expect(mock.callsTo('POST', '/quizzes/jobs')).toHaveLength(1))

    // Step 2: the dashboard re-reads the quiz when the feed says that job
    // reached `ready` (StudentDashboard.tsx:187-189). That is the only caller
    // of loadQuizMutation, and it reads through useSyncExternalStore over the
    // query cache — the same key the feed's sink writes. So writing it here is
    // not a shortcut around the code under test, it IS how the code receives
    // job state; the transport above it is mocked everywhere anyway.
    queryClient.setQueryData(queryKeys.jobs('ml'), {
      jobs: [{ id: 77, kind: 'quiz', status: 'ready', terminal: true, progress_pct: 100 }],
      mode: 'stream',
      changeToken: 1,
    })

    await waitFor(
      () => {
        expect(screen.getByText(/Quiz cap not applied/i)).toBeInTheDocument()
      },
      { timeout: 5_000 },
    )
    // And it names both numbers, so the user can see the discrepancy rather
    // than being told only that something is wrong.
    expect(
      screen.getByText(new RegExp(`153 questions instead of the ${quizMaxQuestions()} requested`)),
    ).toBeInTheDocument()
    // 153 questions means 153 MUI RadioGroups rendering, so this test does real
    // work the other three do not — about 4.3s of it, against a 5s default. That
    // is why it timed out in a full-suite run while passing in isolation: the
    // whole file then competes for the same worker. Raised deliberately, with the
    // cause named, rather than by trimming the payload — the point is that a
    // 153-question response is what an uncapped backend delivers.
  }, 20_000)
})