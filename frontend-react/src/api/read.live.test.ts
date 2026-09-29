/**
 * LIVE tier â€” the read path, against a real backend and a real database.
 *
 * The mocked suite proves policy. This proves plumbing: that the response the
 * server actually sends, parsed by the real client, reaches a real component
 * and becomes visible text. On 2026-09-29 the app's extract worker died with
 * an `IntegrityError` on every click while 297 frontend and 710 backend tests
 * stayed green, because none of them involved a server.
 *
 * What is asserted here is deliberately literal â€” sentinel names from
 * `scripts/seed_live_db.py` â€” so a failure names the exact row that went
 * missing instead of "something rendered".
 */

import { describe, expect, it } from 'vitest'
import { courses } from './courses'
import { lectures } from './lectures'
import { enableLiveBackend } from '../test/live/enableLiveBackend'

enableLiveBackend()

describe('live: the real client reaches a real server', () => {
  it('lists the courses the seeded database actually contains', async () => {
    const rows = await courses.list()

    expect(rows.map((c) => c.course_id).sort()).toEqual(['ml', 'prob'])
    const ml = rows.find((c) => c.course_id === 'ml')
    expect(ml?.total_lectures).toBe(2)
    expect(ml?.total_concepts).toBe(3)
    expect(ml?.has_graph).toBe(true)
  })

  it('lists lectures, and the course_id filter is NOT applied server-side', async () => {
    const rows = await lectures.list('ml')

    // FINDING (2026-09-29): `GET /lectures?course_id=ml` returns every lecture
    // in the database â€” the seeded `prob` lecture comes back too. The wrapper
    // sends course_id, so either the route drops the parameter or the client
    // is expected to filter. The React app hardcodes `selectedCourseId = 'ml'`
    // and never sees the difference, so this has been invisible; it becomes a
    // real bug the moment a second course is selected.
    //
    // Asserted as-is on purpose: this test's job is to record what the server
    // actually does, so the day the filter is fixed, this fails and says so.
    const byCourse = new Map(rows.map((l) => [l.course_id, l.title]))
    expect(byCourse.get('ml')).toBeDefined()
    expect(byCourse.get('prob')).toBeDefined()
    expect(rows.filter((l) => l.course_id === 'ml').map((l) => l.title).sort()).toEqual([
      'Linear Regression',
      'Multiple Regression',
    ])
    for (const l of rows) expect(l.status).toBe('ready')
  })

  it('returns a lectureâ€™s clips as playback URLs, never filesystem paths', async () => {
    const rows = await lectures.list('ml')
    const withClips = rows.find((l) => l.title === 'Linear Regression')!
    const batch = await lectures.clips(withClips.id)

    const names = batch.clips.map((c) => c.concept_name).sort()
    expect(names).toEqual(['Linear Regression', 'Slope'])
    for (const c of batch.clips) {
      // A filesystem path in a payload is a contract failure
      // (ARCHITECTURE Â§3): the backend must hand over a URL a browser can fetch.
      expect(c.url).toMatch(/^\/media\/clips\//)
      expect(c.url).not.toContain('\\')
    }
  })

  it('answers 404-shaped detail for a lecture that does not exist', async () => {
    await expect(lectures.get(999_999)).rejects.toMatchObject({ status: 404 })
  })
})

describe('live: the SSE feed parses a real stream', () => {
  it('receives retry, a full-array snapshot, and keep-alives from /jobs/stream', async () => {
    const base = process.env.VITE_LECGAP_API_URL!
    const controller = new AbortController()
    const res = await fetch(`${base}/jobs/stream`, {
      headers: { Accept: 'text/event-stream' },
      signal: controller.signal,
    })
    expect(res.status).toBe(200)

    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let seen = ''

    // Read until the first real payload lands. A keep-alive-only stream would
    // mean the change-gated snapshot is broken, which is exactly the kind of
    // thing a hand-written fake transport cannot detect.
    while (!seen.includes('event: jobs')) {
      const { value, done } = await reader.read()
      if (done) break
      seen += decoder.decode(value, { stream: true })
      expect(seen.length).toBeLessThan(200_000) // runaway guard
    }
    controller.abort()
    await reader.cancel().catch(() => {})

    expect(seen).toMatch(/retry:\s*\d+/)
    expect(seen).toContain('event: jobs')

    // The payload is a FULL ARRAY, change-gated â€” not one row per event. Twelve
    // jobs starting together arrive as one snapshot; a client that assumed
    // per-row events would break here and nowhere else.
    const dataLine = seen.split('\n').find((l) => l.startsWith('data: '))
    expect(dataLine).toBeDefined()
    const payload = JSON.parse(dataLine!.slice('data: '.length))
    expect(Array.isArray(payload)).toBe(true)
    expect(payload.some((j: { course_id: string }) => j.course_id === 'ml')).toBe(true)
  })
})
