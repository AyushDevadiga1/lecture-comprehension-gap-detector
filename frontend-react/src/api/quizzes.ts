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
  create: (courseId: string, studentId: string, maxQuestions?: number): Promise<QuizOut> =>
    post<QuizOut>('/quizzes', {
      course_id: courseId,
      student_id: studentId,
      ...(maxQuestions ? { max_questions: maxQuestions } : {}),
    }),

  createJob: (courseId: string, studentId: string, maxQuestions?: number): Promise<JobAcceptedOut> =>
    post<JobAcceptedOut>('/quizzes/jobs', {
      course_id: courseId,
      student_id: studentId,
      ...(maxQuestions ? { max_questions: maxQuestions } : {}),
    }),

  submit: (submission: QuizSubmitIn): Promise<QuizSubmitOut> =>
    post<QuizSubmitOut>('/quizzes/submit', submission),

  getRemediation: (studentId: string, courseId: string): Promise<QuizSubmitOut> =>
    get<QuizSubmitOut>(`/students/${studentId}/remediation`, { course_id: courseId }),
}
