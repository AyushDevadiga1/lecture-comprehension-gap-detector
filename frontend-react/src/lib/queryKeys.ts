/**
 * Query keys and the single invalidation rule.
 *
 * REACT_ARCHITECTURE.md §3: keys are `[resource, ...scope]` with the course id
 * in scope, and mutations invalidate **by prefix** through one helper — the
 * direct analogue of `frontend/client.py::invalidate_for_course`, which clears
 * the course and lecture namespaces after any course-affecting write.
 *
 * The rule exists so a panel never hand-rolls an invalidation list. Four such
 * lists had already drifted apart (and none of them cleared `['courses']`, so a
 * newly-created course never appeared in the picker).
 */

import type { QueryClient } from '@tanstack/react-query'

export const queryKeys = {
  courses: () => ['courses'] as const,
  snapshot: (courseId: string) => ['snapshot', courseId] as const,
  graph: (courseId: string) => ['graph', courseId] as const,
  stats: (courseId: string) => ['stats', courseId] as const,
  lectures: (courseId: string) => ['lectures', courseId] as const,
  clips: (lectureId: number) => ['clips', lectureId] as const,
  remediation: (studentId: string) => ['remediation', studentId] as const,
  /** Fed by the SSE feed, never fetched on a timer. See useJobs(). */
  jobs: (courseId: string) => ['jobs', courseId] as const,
  usage: () => ['usage'] as const,
} as const

/**
 * Resources scoped to one course. `['courses']` is unscoped and always cleared.
 */
const COURSE_SCOPED = ['snapshot', 'graph', 'stats', 'lectures'] as const

/**
 * Invalidate every course-scoped read for `courseId`, plus the course list.
 *
 * **Amendment to §3**, recorded deliberately: the rule printed in that document
 * matches `snapshot | graph | stats | lectures` but omits `courses`. That means a
 * freshly-created course does not appear in the Navbar picker until its own TTL
 * (10s) lapses, which is the stale-list-after-write bug the same document is
 * trying to prevent. `courses` is added here.
 *
 * `clips` and `remediation` are deliberately not course-scoped (they are keyed
 * by lecture id and student id); a clip cut invalidates `['lectures', courseId]`
 * and the clip list is refetched by its own key when the lecture panel opens.
 */
export function invalidateCourse(queryClient: QueryClient, courseId: string): void {
  void queryClient.invalidateQueries({ queryKey: queryKeys.courses() })
  void queryClient.invalidateQueries({
    predicate: (query) => {
      const resource = query.queryKey[0]
      if (typeof resource !== 'string') return false
      if (resource === 'courses') return true
      if (!(COURSE_SCOPED as readonly string[]).includes(resource)) return false
      // Unscoped variants (length 1) match; scoped ones must match the course.
      return query.queryKey.length === 1 || query.queryKey[1] === courseId
    },
  })
}
