import { describe, expect, it } from 'vitest'
import { LecGapApiError } from '../api/client'
import {
  capViolation,
  generationError,
  latencySince,
  MAX_QUIZ_QUESTIONS,
  MIN_QUIZ_QUESTIONS,
  quizMaxQuestions,
  submitError,
} from './quiz'

/**
 * Ported from `frontend/panels/quiz.py`; the Python twins are the assertions in
 * `tests/test_frontend_app.py` and the panel's own docstrings.
 */

describe('quizMaxQuestions', () => {
  it('defaults to 15 when the env var is unset', () => {
    // panels/quiz.py:30
    expect(quizMaxQuestions()).toBe(15)
  })

  it('clamps into the range the backend accepts', () => {
    // The backend validates ge=1, le=200, so an out-of-range value is a 422
    // rather than a clamped success.
    expect(quizMaxQuestions()).toBeGreaterThanOrEqual(MIN_QUIZ_QUESTIONS)
    expect(quizMaxQuestions()).toBeLessThanOrEqual(MAX_QUIZ_QUESTIONS)
  })
})

describe('capViolation', () => {
  // panels/quiz.py:47-58
  it('is null when the cap was respected', () => {
    expect(capViolation(15, 15)).toBeNull()
    expect(capViolation(4, 15)).toBeNull()
  })

  it('names both numbers when the backend ignored the cap', () => {
    const msg = capViolation(153, 15)
    expect(msg).toContain('153')
    expect(msg).toContain('15')
    expect(msg).toMatch(/older build/)
  })

  it('says nothing when no cap was requested', () => {
    expect(capViolation(153, 0)).toBeNull()
  })
})

describe('generationError', () => {
  // panels/quiz.py:152-161
  it('explains a 409 as a course already generating', () => {
    const msg = generationError(new LecGapApiError(409, 'A quiz is already being generated'))
    expect(msg).toMatch(/already being generated/i)
    expect(msg).toMatch(/wait for it to finish/i)
  })

  it('explains a 404 as no concepts yet', () => {
    const msg = generationError(new LecGapApiError(404, 'No concepts for course'))
    expect(msg).toMatch(/no concepts yet/i)
    expect(msg).toMatch(/Extract concepts/i)
  })

  it("surfaces the backend's detail for anything else", () => {
    expect(generationError(new LecGapApiError(500, 'Internal server error'))).toBe(
      'Internal server error',
    )
  })

  it('falls back rather than showing a status code', () => {
    expect(generationError(new Error('boom'))).toBe('boom')
    expect(generationError('not an error', 'fallback')).toBe('fallback')
  })
})

describe('submitError', () => {
  // panels/quiz.py:132-134
  it('turns a 404 into "regenerate", not a dead end', () => {
    const msg = submitError(new LecGapApiError(404, 'Question 9 not found'))
    expect(msg).toMatch(/regenerated while you were answering/i)
    expect(msg).toMatch(/generate the quiz again/i)
  })

  it('explains a cross-course 400', () => {
    expect(submitError(new LecGapApiError(400, 'cross-course'))).toMatch(/different course/i)
  })

  it("surfaces the backend's detail otherwise", () => {
    expect(submitError(new LecGapApiError(500, 'Internal server error'))).toBe(
      'Internal server error',
    )
  })
})

describe('latencySince', () => {
  // panels/quiz.py:118-122
  it('is the mean seconds per answer, rounded to 2dp', () => {
    const now = Date.now()
    // 4 questions over 20s -> 5s each
    expect(latencySince(now - 20_000, 4)).toBe(5)
  })

  it('is 0 rather than NaN/Infinity at the edges', () => {
    expect(latencySince(0, 3)).toBe(0)
    expect(latencySince(Date.now(), 0)).toBe(0)
    expect(latencySince(Date.now(), -1)).toBe(0)
  })
})
