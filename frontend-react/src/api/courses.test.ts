import { describe, expect, it } from 'vitest'
import { courses } from './courses'
import { mockFetch } from '../test/fetchMock'

/**
 * The verb regression. `courses.buildGraph` issued a **GET** against a path
 * whose build endpoint is POST; the GET on the same path is a *read* of an
 * existing graph which takes no `lecture_id` and 404s when absent. So
 * "Rebuild Prerequisite DAG" either did nothing (graph present -> read
 * succeeded, no job created) or failed silently (no graph -> 404, and the
 * mutation had no onError).
 */

describe('courses.buildGraph', () => {
  it('POSTs, and does not GET', async () => {
    const mock = mockFetch([
      { method: 'POST', path: '/courses/ML/graph', status: 202, json: { status: 'queued', course_id: 'ML', job_id: 7 } },
    ])

    const res = await courses.buildGraph('ML')
    expect(res.job_id).toBe(7)

    const call = mock.calls[0]!
    expect(call.method).toBe('POST')
    // The read endpoint is a different verb on the same path, so the method is
    // the whole assertion.
    expect(call.url).not.toContain('lecture_id')
  })

  it('passes lecture_id as a query parameter, not a body', async () => {
    // The backend declares it as a query param (courses.py:182); a JSON body
    // would be silently ignored.
    const mock = mockFetch([
      { method: 'POST', path: '/courses/ML/graph', status: 202, json: { status: 'queued', course_id: 'ML', job_id: 8 } },
    ])

    await courses.buildGraph('ML', 42)

    const call = mock.calls[0]!
    expect(call.url).toContain('lecture_id=42')
    expect(call.body ?? null).toBeNull()
  })
})

describe('courses.reads', () => {
  it('graph() is still a GET of the existing graph', async () => {
    const mock = mockFetch([
      {
        path: '/courses/ML/graph',
        json: { course_id: 'ML', nodes: [], edges: [], node_count: 0, edge_count: 0, is_dag: true, topological_order: [] },
      },
    ])
    await courses.graph('ML')
    expect(mock.calls[0]!.method).toBe('GET')
  })
})
