/**
 * Domain wrapper — courses.
 * Feature components import from here; they never call client.get directly.
 */
import { get, post, del } from './client'
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

  /**
   * Queue a graph build. **POST**, not GET: `POST /courses/{id}/graph` is the
   * build endpoint (202 + `job_id`) and the same path under GET is a *read* of
   * an existing graph, which takes no `lecture_id` and 404s when absent.
   *
   * This was a `get()`, so "Rebuild Prerequisite DAG" either did nothing at all
   * (a graph already existed, so the read succeeded, no job was created) or
   * failed silently — the mutation had no `onError` either. The Streamlit engine
   * had this right all along (`panels/ingest.py:119-120`).
   */
  buildGraph: (courseId: string, lectureId?: number): Promise<CourseBuildOut> =>
    post<CourseBuildOut>(`/courses/${courseId}/graph`, undefined, {
      lecture_id: lectureId,
    }),

  delete: (courseId: string): Promise<CourseDeleteOut> =>
    del(`/courses/${courseId}`),
}
