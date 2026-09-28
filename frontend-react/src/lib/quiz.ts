/**
 * Quiz generation: the cap, the async path, and honest failure messages.
 *
 * ## Why the cap exists
 *
 * `POST /quizzes` generates one LLM call per concept, fanned out six-wide,
 * inline. The `ml` course has 153 concepts (`WORKLOG.md`, 2026-09-13 run), so an
 * uncapped request is ~153 serial-ish calls behind one blocking POST — the
 * multi-minute frozen UI that Engine 2 exists to end, and the thing the
 * Streamlit panel's `LECGAP_QUIZ_MAX_QUESTIONS` (default 15) was added to stop.
 * The React app had the parameter wired in `api/quizzes.ts` but never passed it,
 * so the cap silently did not apply.
 *
 * The cap is a *request*: the backend does the even-spread sampling
 * (`_spread_sample`, `backend/api/routes/quizzes.py:187-197`) so the questions
 * cover the whole lecture rather than its opening concepts. The client must not
 * sample anything itself.
 */

import { LecGapApiError } from '../api/client'

/** `panels/quiz.py:30` — `_DEFAULT_MAX_QUESTIONS = 15` */
const DEFAULT_MAX_QUESTIONS = 15

/**
 * The backend validates `max_questions` as `ge=1, le=200`
 * (`backend/api/routes/quizzes.py:77-78`), so a value outside that range is a
 * 422 rather than a clamped success.
 */
export const MIN_QUIZ_QUESTIONS = 1
export const MAX_QUIZ_QUESTIONS = 200

/**
 * The cap, read from `VITE_LECGAP_QUIZ_MAX_QUESTIONS` with the same precedence
 * as `quiz_max_questions()`: empty or unparseable falls back to 15, and
 * anything below 1 is clamped rather than sent as a 422.
 */
export function quizMaxQuestions(): number {
  const raw = (import.meta.env.VITE_LECGAP_QUIZ_MAX_QUESTIONS as string | undefined)?.trim()
  if (!raw) return DEFAULT_MAX_QUESTIONS
  const parsed = Number(raw)
  if (!Number.isFinite(parsed)) return DEFAULT_MAX_QUESTIONS
  return Math.min(MAX_QUIZ_QUESTIONS, Math.max(MIN_QUIZ_QUESTIONS, Math.trunc(parsed)))
}

/**
 * `cap_violation` from `panels/quiz.py:47-58`, ported verbatim.
 *
 * A backend predating the cap ignores the field and regenerates one question per
 * concept. Say so, rather than quietly rendering a 153-question form the reader
 * has to scroll through.
 */
export function capViolation(returned: number, requested: number): string | null {
  if (requested && returned > requested) {
    return (
      `The backend returned ${returned} questions instead of the ` +
      `${requested} requested, so it is an older build — restart it ` +
      `to pick up the quiz cap.`
    )
  }
  return null
}

/**
 * `_generation_error` from `panels/quiz.py:152-161`, ported verbatim.
 *
 * A 409 and a 404 both mean something the user can act on, and neither is
 * legible as a raw status code.
 */
export function generationError(err: unknown, fallback = 'Quiz generation failed.'): string {
  if (err instanceof LecGapApiError) {
    if (err.status === 409) {
      return (
        'A quiz is already being generated for this course — wait for it ' +
        'to finish, then press Generate again.'
      )
    }
    if (err.status === 404) {
      return (
        'This course has no concepts yet, so there is nothing to quiz. ' +
        'Extract concepts from a ready lecture first.'
      )
    }
    return err.detail || fallback
  }
  return err instanceof Error && err.message ? err.message : fallback
}

/**
 * Submit-time messages. `panels/quiz.py:132-134`:
 * "The quiz on the server was regenerated while you were answering — please
 * generate the quiz again."
 *
 * A 404 on submit is the *friendly* version of a race: another student
 * regenerated the course's questions and this draft's ids no longer exist. It
 * must never surface as a dead end.
 */
export function submitError(err: unknown, fallback = 'Quiz submission failed.'): string {
  if (err instanceof LecGapApiError) {
    if (err.status === 404) {
      return (
        'The quiz on the server was regenerated while you were answering — ' +
        'please generate the quiz again.'
      )
    }
    if (err.status === 400) {
      return 'That answer belongs to a different course, so it was not accepted.'
    }
    return err.detail || fallback
  }
  return err instanceof Error && err.message ? err.message : fallback
}

/**
 * `latency_s` per answer, as `panels/quiz.py:118-122` computes it: mean seconds
 * from serving the quiz to submitting, stamped on every answer. The backend
 * stores it per response, so it is what makes "how long did this student take"
 * answerable later.
 */
export function latencySince(renderTimestampMs: number, answerCount: number): number {
  if (!renderTimestampMs || answerCount <= 0) return 0
  return Math.round(((Date.now() - renderTimestampMs) / 1000 / answerCount) * 100) / 100
}
