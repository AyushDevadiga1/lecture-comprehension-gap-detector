/**
 * Domain wrapper — quizzes.
 * Feature components import from here; they never call client.* directly.
 */
import { get, post } from './client'
import type {
  QuizOut,
  QuizSubmitIn,
  QuizSubmitOut,
  JobAcceptedOut,
} from './types'

export const quizzes = {
  /**
   * Queue generation and return a job id. The endpoint a UI should use:
   * generation is one LLM call per question and the synchronous POST froze the
   * page for minutes. Fetch the questions with `current()` once the job is done.
   */
  createJob: (courseId: string, studentId: string, maxQuestions?: number): Promise<JobAcceptedOut> =>
    post<JobAcceptedOut>('/quizzes/jobs', {
      course_id: courseId,
      student_id: studentId,
      ...(maxQuestions ? { max_questions: maxQuestions } : {}),
    }),

  /**
   * Read the quiz already generated for a course, without regenerating.
   * 404 when nothing has been generated yet.
   */
  current: (courseId: string, studentId: string): Promise<QuizOut> =>
    get<QuizOut>('/quizzes', { course_id: courseId, student_id: studentId }),

  /**
   * Blocking, destructive generation. Kept for API and smoke-test parity only —
   * `plan/FRONTEND_API_CONTRACT.md` §2 records it as the endpoint that must not
   * be used from a UI. Prefer `createJob` + `current`.
   */
  create: (courseId: string, studentId: string, maxQuestions?: number): Promise<QuizOut> =>
    post<QuizOut>('/quizzes', {
      course_id: courseId,
      student_id: studentId,
      ...(maxQuestions ? { max_questions: maxQuestions } : {}),
    }),

  submit: (submission: QuizSubmitIn): Promise<QuizSubmitOut> =>
    post<QuizSubmitOut>('/quizzes/submit', submission),

  getRemediation: (studentId: string, courseId: string): Promise<QuizSubmitOut> =>
    get<QuizSubmitOut>(`/students/${studentId}/remediation`, { course_id: courseId }),
}
