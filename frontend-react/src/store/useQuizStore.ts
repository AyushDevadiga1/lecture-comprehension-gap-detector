import { create } from 'zustand'
import type { QuizOut, QuizSubmitOut } from '../api/types'

/**
 * The in-progress quiz. §2: "if losing it loses information the server has, it
 * is server state; if losing it loses nothing but the user's typing, it is UI
 * state."
 *
 * The draft is UI state. The questions themselves are the server's, and are
 * re-readable with `GET /quizzes`; what is only here is the *selections*, and
 * the id set they point at. That is exactly why a background job completing
 * cannot disturb it — the job invalidates the graph and lecture keys, and none
 * of that is the draft.
 *
 * The draft holds the question ids it was served, and submit echoes them back.
 * If the server regenerates the course's questions, those ids go stale — which
 * is the condition `submitError` turns into "generate the quiz again" instead of
 * a 404 dead end.
 */

export interface QuizDraft {
  quiz: QuizOut
  /** course_id the quiz was served for; a course change invalidates the draft. */
  courseId: string
  studentId: string
  /** question_id -> selected option */
  answers: Record<number, string>
  /** When the questions were served, for `latency_s`. */
  renderedAt: number
}

interface QuizState {
  draft: QuizDraft | null
  result: QuizSubmitOut | null
  /** Set when the draft is dropped so the page can explain why. */
  clearedReason: string | null

  start: (draft: QuizDraft) => void
  select: (questionId: number, option: string) => void
  /** Drop the draft and keep the graded result. */
  finish: (result: QuizSubmitOut) => void
  /** Drop the draft because it no longer applies, with a reason to show. */
  clear: (reason?: string | null) => void
  reset: () => void
}

export const useQuizStore = create<QuizState>((set) => ({
  draft: null,
  result: null,
  clearedReason: null,

  start: (draft) => set({ draft, result: null, clearedReason: null }),

  select: (questionId, option) =>
    set((state) => {
      if (!state.draft) return state
      return { draft: { ...state.draft, answers: { ...state.draft.answers, [questionId]: option } } }
    }),

  finish: (result) => set({ draft: null, result, clearedReason: null }),

  clear: (reason = null) => set({ draft: null, result: null, clearedReason: reason }),

  reset: () => set({ draft: null, result: null, clearedReason: null }),
}))

/** The draft, or null if it is for a different course. §2's course-change rule. */
export function draftForCourse(state: QuizState, courseId: string | null): QuizDraft | null {
  if (!state.draft || !courseId) return null
  return state.draft.courseId === courseId ? state.draft : null
}
