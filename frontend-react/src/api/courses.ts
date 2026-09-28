/**
 * Domain wrapper — courses.
 * Feature components import from here; they never call client.get directly.
 */
import { get, del } from './client'
import type {
  CourseSummaryOut,
  CourseGraphOut,
  CourseStats,
  CourseSnapshot,
  CourseBuildOut,
  CourseDeleteOut,
} from './types'

export const courses = {
  list: (): Promise<CourseSummaryOut[]> => get('/courses'),

  graph: (courseId: string): Promise<CourseGraphOut> =>
    get(`/courses/${courseId}/graph`),

  stats: (courseId: string): Promise<CourseStats> =>
    get(`/courses/${courseId}/stats`),

  snapshot: (courseId: string): Promise<CourseSnapshot> =>
    get(`/courses/${courseId}/snapshot`),

  buildGraph: (courseId: string, lectureId?: number): Promise<CourseBuildOut> => {
    const params = lectureId !== undefined ? `?lecture_id=${lectureId}` : ''
    return get<CourseBuildOut>(`/courses/${courseId}/graph${params}`)
  },

  delete: (courseId: string): Promise<CourseDeleteOut> =>
    del(`/courses/${courseId}`),
}
