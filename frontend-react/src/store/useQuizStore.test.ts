import { beforeEach, describe, expect, it } from 'vitest'
import { useQuizStore, draftForCourse } from './useQuizStore'
import type { QuizOut } from '../api/types'

/**
 * §2: the draft is UI state, holds the ids it was served, and survives a
 * background job completing. The last property is the one the roadmap's parity
 * checklist calls out — "start a lecture job mid-quiz, finish the quiz, nothing
 * was regenerated or lost" — and the Streamlit engine needed a dedicated
 * `completed` session record plus a `drain_ready` to achieve it.
 */

const quiz = (id = 1): QuizOut => ({
  quiz_id: id,
  course_id: 'ML',
  student_id: 's1',
  questions: [{ id: 10, concept: 'A', question: 'q?', options: ['a', 'b', 'c'] }],
})

const draft = (courseId = 'ML') => ({
  quiz: quiz(),
  courseId,
  studentId: 's1',
  answers: {},
  renderedAt: 1_700_000_000_000,
})

describe('useQuizStore', () => {
  beforeEach(() => useQuizStore.getState().reset())

  it('starts empty', () => {
    expect(useQuizStore.getState().draft).toBeNull()
    expect(useQuizStore.getState().result).toBeNull()
  })

  it('records the question ids it was served', () => {
    useQuizStore.getState().start(draft())
    expect(useQuizStore.getState().draft?.quiz.questions[0]?.id).toBe(10)
  })

  it('keeps a selection across unrelated updates', () => {
    useQuizStore.getState().start(draft())
    useQuizStore.getState().select(10, 'b')
    // A job completing is a cache invalidation, not a store write — the draft
    // is simply not involved.
    expect(useQuizStore.getState().draft?.answers[10]).toBe('b')
  })

  it('overwrites a selection for the same question', () => {
    useQuizStore.getState().start(draft())
    useQuizStore.getState().select(10, 'b')
    useQuizStore.getState().select(10, 'c')
    expect(useQuizStore.getState().draft?.answers[10]).toBe('c')
  })

  it('ignores a selection with no draft', () => {
    useQuizStore.getState().select(10, 'b')
    expect(useQuizStore.getState().draft).toBeNull()
  })

  it('drops the draft on submit, keeping the graded result', () => {
    useQuizStore.getState().start(draft())
    useQuizStore.getState().select(10, 'b')
    useQuizStore.getState().finish({
      quiz_id: 1,
      student_id: 's1',
      score: 1,
      total: 1,
      remediation: [],
      feedback: [],
    })
    const s = useQuizStore.getState()
    expect(s.draft).toBeNull()
    expect(s.result?.score).toBe(1)
  })

  it('records a reason when the draft is cleared', () => {
    useQuizStore.getState().start(draft())
    useQuizStore.getState().clear('course changed')
    expect(useQuizStore.getState().clearedReason).toBe('course changed')
    expect(useQuizStore.getState().draft).toBeNull()
  })
})

describe('draftForCourse', () => {
  beforeEach(() => useQuizStore.getState().reset())

  it('returns the draft for the current course', () => {
    useQuizStore.getState().start(draft('ML'))
    expect(draftForCourse(useQuizStore.getState(), 'ML')).not.toBeNull()
  })

  it('withholds a draft belonging to another course', () => {
    // panels/quiz.py:99-103 — switching courses clears the quiz rather than
    // showing the previous course's questions.
    useQuizStore.getState().start(draft('ML'))
    expect(draftForCourse(useQuizStore.getState(), 'prob')).toBeNull()
  })

  it('withholds the draft when no course is selected', () => {
    useQuizStore.getState().start(draft('ML'))
    expect(draftForCourse(useQuizStore.getState(), null)).toBeNull()
  })
})
