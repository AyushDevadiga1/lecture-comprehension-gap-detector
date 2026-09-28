/**
 * Domain wrapper — jobs.
 * Feature components import from here; they never call client.* directly.
 */
import { get, post } from './client'
import type { JobOut, JobListOut } from './types'

export const jobs = {
  list: (courseId?: string, activeOnly?: boolean, limit = 100): Promise<JobListOut> =>
    get('/jobs', { course_id: courseId, active_only: activeOnly, limit }),

  get: (jobId: number): Promise<JobOut> => get(`/jobs/${jobId}`),

  cancel: (jobId: number): Promise<JobOut> => post(`/jobs/${jobId}/cancel`),
}
