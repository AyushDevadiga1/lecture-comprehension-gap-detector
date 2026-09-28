import { describe, expect, it } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { invalidateCourse, queryKeys } from './queryKeys'

/**
 * The one invalidation rule. REACT_ARCHITECTURE.md §3: mutations invalidate by
 * prefix through a single helper, "a panel never hand-rolls an invalidation
 * list" — the direct analogue of `client.invalidate_for_course`.
 */

const client = () => new QueryClient()

const seed = (qc: QueryClient, key: readonly unknown[]) => {
  qc.setQueryData(key, { seeded: true })
}

/** Query keys marked invalid, via the query cache's own record. */
function invalidatedKeys(qc: QueryClient): string[] {
  return qc
    .getQueryCache()
    .findAll()
    .filter((q) => q.state.isInvalidated)
    .map((q) => JSON.stringify(q.queryKey))
}

describe('queryKeys', () => {
  it('scopes every course-scoped read to the course id', () => {
    expect(queryKeys.snapshot('ML')).toEqual(['snapshot', 'ML'])
    expect(queryKeys.graph('ML')).toEqual(['graph', 'ML'])
    expect(queryKeys.stats('ML')).toEqual(['stats', 'ML'])
    expect(queryKeys.lectures('ML')).toEqual(['lectures', 'ML'])
    expect(queryKeys.jobs('ML')).toEqual(['jobs', 'ML'])
  })
})

describe('invalidateCourse', () => {
  it('invalidates every course-scoped key for that course', async () => {
    const qc = client()
    seed(qc, queryKeys.snapshot('ML'))
    seed(qc, queryKeys.graph('ML'))
    seed(qc, queryKeys.stats('ML'))
    seed(qc, queryKeys.lectures('ML'))

    invalidateCourse(qc, 'ML')
    await Promise.resolve()

    expect(invalidatedKeys(qc)).toHaveLength(4)
  })

  it('leaves another course untouched', async () => {
    const qc = client()
    seed(qc, queryKeys.snapshot('prob'))

    invalidateCourse(qc, 'ML')
    await Promise.resolve()

    expect(invalidatedKeys(qc)).toEqual([])
  })

  it('clears the course list, so a new course appears in the picker', async () => {
    // The amendment to §3: the printed rule omits `courses`, which reproduces
    // the stale-list-after-write bug the document is trying to prevent.
    const qc = client()
    seed(qc, queryKeys.courses())

    invalidateCourse(qc, 'ML')
    await Promise.resolve()

    expect(invalidatedKeys(qc)).toEqual([JSON.stringify(['courses'])])
  })

  it('invalidates an unscoped course-scoped key (length 1)', async () => {
    const qc = client()
    seed(qc, ['lectures'])

    invalidateCourse(qc, 'ML')
    await Promise.resolve()

    expect(invalidatedKeys(qc)).toEqual([JSON.stringify(['lectures'])])
  })

  it('does not invalidate the jobs key, which the SSE feed owns', async () => {
    // The feed writes ['jobs', courseId]; marking it stale would invite React
    // Query to refetch it, and its queryFn never fetches.
    const qc = client()
    seed(qc, queryKeys.jobs('ML'))

    invalidateCourse(qc, 'ML')
    await Promise.resolve()

    expect(invalidatedKeys(qc)).toEqual([])
  })

  it('does not invalidate clips or remediation, which are not course-scoped', async () => {
    const qc = client()
    seed(qc, queryKeys.clips(4))
    seed(qc, queryKeys.remediation('s1'))

    invalidateCourse(qc, 'ML')
    await Promise.resolve()

    expect(invalidatedKeys(qc)).toEqual([])
  })
})
