/**
 * The quiz cap must be ON THE WIRE, not merely computed.
 *
 * ## The bug this file exists for
 *
 * `src/lib/quiz.ts` documents it directly: the React app had `max_questions`
 * wired into `api/quizzes.ts` and *never passed it*, so the cap silently did
 * not apply. `POST /quizzes` generates one LLM call per concept; the `ml` course
 * has 153 of them, so an uncapped request is the multi-minute frozen UI this
 * rebuild exists to end.
 *
 * Every existing test would still pass with the parameter deleted. `quiz.test.ts`
 * proves `quizMaxQuestions()` returns 15 — a pure function of an env var,
 * asked nothing about the request. The backend's `_spread_sample` is well
 * covered for the 153/15 case, which proves the sampling is correct and says
 * nothing about whether it was ever asked for.
 *
 * So this asserts the one thing the chain needs and nothing had checked: the
 * field is present in the body the client actually sends.
 */
import { describe, expect, it } from 'vitest'
import { quizzes } from './quizzes'
import { mockFetch } from '../test/fetchMock'
import { quizMaxQuestions } from '../lib/quiz'

describe('the quiz cap reaches the wire', () => {
  it('createJob sends max_questions', async () => {
    const mock = mockFetch([
      { method: 'POST', path: '/quizzes/jobs', status: 202, json: { job_id: 11, status: 'queued' } },
    ])

    await quizzes.createJob('ml', 's1', 15)

    expect(mock.calls[0]!.body).toMatchObject({ max_questions: 15 })
  })

  it('create (the blocking endpoint) sends it too', async () => {
    // Two endpoints, one cap. If only the async path was fixed, a caller
    // reaching for `create` would quietly get 153 questions.
    const mock = mockFetch([
      { method: 'POST', path: '/quizzes', json: { course_id: 'ml', student_id: 's1', questions: [] } },
    ])

    await quizzes.create('ml', 's1', 15)

    expect(mock.calls[0]!.body).toMatchObject({ max_questions: 15 })
  })

  it('sends exactly what the app computed, not a hard-coded 15', async () => {
    // A test asserting the literal 15 passes even if the plumbing between
    // `quizMaxQuestions()` and the request is severed. This one is about the
    // seam: whatever the cap resolves to is what must be sent.
    const mock = mockFetch([
      { method: 'POST', path: '/quizzes/jobs', status: 202, json: { job_id: 12, status: 'queued' } },
    ])

    await quizzes.createJob('ml', 's1', quizMaxQuestions())

    expect((mock.calls[0]!.body as { max_questions: number }).max_questions).toBe(
      quizMaxQuestions(),
    )
  })

  it('a cap of 1 is sent, not dropped as falsy', async () => {
    // `createJob` spreads `...(maxQuestions ? { max_questions } : {})`, so 0
    // vanishes. 0 is already rejected upstream (the backend takes `ge=1`), but
    // the conditional spread is exactly the shape that loses a value silently,
    // and it is the reason this file asserts the field's presence rather than
    // trusting the spread. 1 is the smallest legitimate cap and must survive.
    const mock = mockFetch([
      { method: 'POST', path: '/quizzes/jobs', status: 202, json: { job_id: 13, status: 'queued' } },
    ])

    await quizzes.createJob('ml', 's1', 1)

    expect(mock.calls[0]!.body).toMatchObject({ max_questions: 1 })
  })

  it('omits max_questions only when no cap was given', async () => {
    // The absence is meaningful: an uncapped request is the bug. So the omit
    // path is pinned too, so a future "always send something" fix cannot start
    // sending a default the caller never asked for.
    const mock = mockFetch([
      { method: 'POST', path: '/quizzes/jobs', status: 202, json: { job_id: 14, status: 'queued' } },
    ])

    await quizzes.createJob('ml', 's1')

    expect(mock.calls[0]!.body).not.toHaveProperty('max_questions')
  })
})

describe('the rest of the quiz surface', () => {
  it('current() reads the generated quiz with both identifiers', async () => {
    const mock = mockFetch([
      { path: '/quizzes', json: { course_id: 'ml', student_id: 's1', questions: [] } },
    ])

    await quizzes.current('ml', 's1')

    const call = mock.calls[0]!
    expect(call.method).toBe('GET')
    expect(call.url).toContain('course_id=ml')
    expect(call.url).toContain('student_id=s1')
  })

  it('submit POSTs the answers to /quizzes/submit', async () => {
    const mock = mockFetch([{ method: 'POST', path: '/quizzes/submit', json: { quiz_id: 3 } }])

    await quizzes.submit({
      course_id: 'ml',
      student_id: 's1',
      answers: [{ question_id: 1, selected: 'a', latency_s: 2.5 }],
    })

    const call = mock.callsTo('POST', '/quizzes/submit')[0]!
    // `latency_s` is per-answer and the backend stores it to answer "how long
    // did this student take" later, so it must not be flattened or dropped.
    expect(call.body).toMatchObject({
      answers: [{ question_id: 1, selected: 'a', latency_s: 2.5 }],
    })
  })
})