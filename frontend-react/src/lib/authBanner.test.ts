import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearAuthBanner,
  createQueryClient,
  getAuthBanner,
  isUnauthorized,
  subscribeAuthBanner,
} from './authBanner'
import { LecGapApiError } from '../api/client'
import { courses as coursesApi } from '../api/courses'
import { mockFetch } from '../test/fetchMock'

/**
 * §6 and the roadmap's non-negotiables: "401 = one banner, never a dead 'no
 * courses' state". Before this, a key-guarded backend 401'd the course query
 * and the Navbar rendered "No courses found" — which reads as *your data is
 * gone*, not *you are not authorised*.
 */

describe('the 401 banner', () => {
  beforeEach(() => clearAuthBanner())

  it('starts clear', () => {
    expect(getAuthBanner().message).toBeNull()
  })

  it('raises on a 401 from a query', async () => {
    mockFetch([{ path: '/courses', status: 401, json: { detail: 'Unauthorized' } }])
    const qc = createQueryClient()

    // Through the real wrapper, because that is what throws a LecGapApiError —
    // the handler keys on the typed error, not on a status code it re-reads.
    await qc.fetchQuery({ queryKey: ['courses'], queryFn: () => coursesApi.list() }).catch(() => {})

    expect(getAuthBanner().message).toMatch(/requires an API key/i)
  })

  it('raises on a 401 from a mutation', async () => {
    mockFetch([{ method: 'POST', path: '/courses/ML/graph', status: 401, json: { detail: 'Unauthorized' } }])
    const qc = createQueryClient()

    // Driven through the real MutationCache, which is where onError is wired.
    const mutation = qc
      .getMutationCache()
      .build(qc, { mutationKey: ['t'], mutationFn: () => coursesApi.buildGraph('ML') })
    await mutation.execute(undefined).catch(() => {})

    expect(getAuthBanner().message).toMatch(/requires an API key/i)
  })

  it('stays clear for a non-401 failure', async () => {
    mockFetch([{ path: '/courses', status: 500, json: { detail: 'Internal server error' } }])
    const qc = createQueryClient()

    await qc.fetchQuery({ queryKey: ['courses'], queryFn: () => coursesApi.list() }).catch(() => {})

    expect(getAuthBanner().message).toBeNull()
  })

  it('stays clear for a 404, which is an honest "no graph yet"', async () => {
    mockFetch([{ path: '/courses/ML/graph', status: 404, json: { detail: 'No graph for this course' } }])
    const qc = createQueryClient()

    await qc.fetchQuery({ queryKey: ['g'], queryFn: () => coursesApi.graph('ML') }).catch(() => {})

    expect(getAuthBanner().message).toBeNull()
  })

  it('is sticky: a later success does not clear it', async () => {
    mockFetch([
      { path: '/courses', status: 401, json: { detail: 'Unauthorized' } },
      { path: '/courses/ML/snapshot', json: { exists: true, course_id: 'ML' } },
    ])
    const qc = createQueryClient()

    await qc.fetchQuery({ queryKey: ['courses'], queryFn: () => coursesApi.list() }).catch(() => {})
    expect(getAuthBanner().message).not.toBeNull()

    // The confusing part is precisely that a subsequent read succeeds, so the
    // banner must not quietly retract.
    await qc.fetchQuery({ queryKey: ['s'], queryFn: () => coursesApi.snapshot('ML') })
    expect(getAuthBanner().message).not.toBeNull()
  })

  it('notifies subscribers and can be cleared', () => {
    let calls = 0
    const off = subscribeAuthBanner(() => {
      calls += 1
    })
    clearAuthBanner()
    expect(calls).toBe(1)
    expect(getAuthBanner().message).toBeNull()
    off()
  })
})

describe('isUnauthorized', () => {
  it('is true only for a 401 LecGapApiError', () => {
    expect(isUnauthorized(new LecGapApiError(401, 'Unauthorized'))).toBe(true)
    expect(isUnauthorized(new LecGapApiError(403, 'nope'))).toBe(false)
    expect(isUnauthorized(new Error('401'))).toBe(false)
    expect(isUnauthorized('401')).toBe(false)
  })
})
