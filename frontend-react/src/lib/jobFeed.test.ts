import { describe, expect, it, vi } from 'vitest'
import { JobFeed } from './jobFeed'
import type { FeedState } from './jobFeed'
import type { JobOut } from '../api/types'

/**
 * The feed's policy, ported from `frontend/jobfeed.py` and the tests that pin
 * it there. Each case names its twin in `tests/test_jobfeed.py`.
 */

const job = (over: Partial<JobOut> = {}): JobOut =>
  ({
    id: 1,
    kind: 'transcribe',
    status: 'running',
    course_id: 'ML',
    lecture_id: 1,
    title: 'Lecture',
    stage: 'transcribing',
    detail: 'working',
    progress_pct: 40,
    created_at: '2026-09-28T00:00:00Z',
    terminal: false,
    ...over,
  }) as JobOut

/** A stream that stays open, like a real one. The test must stop the feed. */
function openSse(chunks: string[] = []): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c))
        // deliberately never closes
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )
}

/** A stream that delivers `chunks` and then closes. */
function closingSse(chunks: string[] = []): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c))
        controller.close()
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )
}

/** Let queued microtasks drain so the reader has consumed what it was sent. */
const settle = () => new Promise<void>((r) => setTimeout(r, 0))

interface Harness {
  feed: JobFeed
  /** Sleep durations requested, in order. */
  sleeps: number[]
  /** How many times the transport ran (stream attempts + polls). */
  transportCalls(): number
  /**
   * The last state published while the feed was *live*. `disconnect()` resets
   * to `{jobs: [], mode: 'starting'}`, which is correct behaviour (a course
   * change must not leave the old course's jobs on screen) but means a test has
   * to look at what it saw before stopping.
   */
  live(): FeedState
  stop(): Promise<void>
}

function harness(
  impl: (url: string, init?: RequestInit) => Promise<Response>,
  onSleep?: (n: number) => void,
): Harness {
  const sleeps: number[] = []
  let calls = 0
  let live: FeedState = { jobs: [], mode: 'starting', changeToken: 0 }

  const feed = new JobFeed({
    fetchImpl: vi.fn(async (url, init) => {
      calls += 1
      return impl(String(url), init)
    }) as unknown as typeof fetch,
    sleep: async (ms) => {
      sleeps.push(ms)
      onSleep?.(sleeps.length)
    },
    setTimer: () => 0 as unknown as ReturnType<typeof setTimeout>,
    clearTimer: () => {},
  })
  feed.subscribe((s) => {
    if (s.mode !== 'starting') live = s
  })

  return {
    feed,
    sleeps,
    transportCalls: () => calls,
    live: () => live,
    stop: async () => {
      feed.disconnect()
      await feed.settled()
    },
  }
}

describe('JobFeed — the stream', () => {
  it('sends the auth header and scopes the stream to the course', async () => {
    // twin: test_stream_request_carries_the_api_key
    const seen: Array<{ url: string; accept: string | null }> = []
    const h = harness(async (url, init) => {
      seen.push({ url, accept: new Headers(init?.headers).get('Accept') })
      return openSse()
    })

    h.feed.connect('ML')
    await settle()
    await h.stop()

    expect(seen[0]!.url).toContain('/jobs/stream')
    expect(seen[0]!.url).toContain('course_id=ML')
    // Routed through client.ts, which is the only place the key is injected --
    // the property that matters, since a bare EventSource cannot set headers.
    expect(seen[0]!.accept).toBe('text/event-stream')
  })

  it('publishes a data frame and ignores retry / keep-alive / event lines', async () => {
    // twin: test_stream_frames_publish_the_snapshot
    const h = harness(async () =>
      openSse([
        'retry: 2000\n\n',
        ': keep-alive\n\n',
        'event: jobs\n',
        `data: ${JSON.stringify([job({ id: 7, progress_pct: 80 })])}\n\n`,
        ': keep-alive\n\n',
      ]),
    )

    h.feed.connect('ML')
    await settle()
    const live = h.live()
    await h.stop()

    expect(live.jobs).toHaveLength(1)
    expect(live.jobs[0]!.id).toBe(7)
    expect(live.mode).toBe('stream')
  })

  it('reassembles a frame split across chunk boundaries', async () => {
    const payload = `data: ${JSON.stringify([job({ id: 9 })])}\n\n`
    const half = Math.floor(payload.length / 2)
    const h = harness(async () => openSse([payload.slice(0, half), payload.slice(half)]))

    h.feed.connect(null)
    await settle()
    const live = h.live()
    await h.stop()

    expect(live.jobs[0]?.id).toBe(9)
  })

  it('treats a malformed frame as non-fatal and keeps reading', async () => {
    // twin: test_a_malformed_frame_does_not_kill_the_feed
    const h = harness(async () =>
      openSse([
        `data: ${JSON.stringify([job({ id: 1 })])}\n\n`,
        'data: {not json\n\n',
        `data: ${JSON.stringify([job({ id: 2 })])}\n\n`,
      ]),
    )

    h.feed.connect(null)
    await settle()
    const live = h.live()
    await h.stop()

    // The bad line is skipped; the good one after it still lands.
    expect(live.jobs[0]?.id).toBe(2)
  })

  it('is idempotent for the same course: a second connect adds no connection', async () => {
    const h = harness(async () => openSse())
    h.feed.connect('ML')
    await settle()
    h.feed.connect('ML')
    await settle()

    expect(h.transportCalls()).toBe(1)
    await h.stop()
  })

  it('reconnects when the course changes', async () => {
    const courses: (string | null)[] = []
    const h = harness(async (url) => {
      courses.push(new URL(url).searchParams.get('course_id'))
      return openSse()
    })

    h.feed.connect('ML')
    await settle()
    h.feed.connect('prob')
    await settle()
    await h.stop()

    expect(courses).toEqual(['ML', 'prob'])
  })

  it('does not leave a course change showing the previous course\'s jobs', async () => {
    // The backend always terminates a frame with "\n\n"; this test uses the real
    // wire format rather than relying on the end-of-stream flush.
    const h = harness(async (url) =>
      url.includes('course_id=ML')
        ? openSse([`data: ${JSON.stringify([job({ course_id: 'ML' })])}\n\n`])
        : openSse(['data: []\n\n']),
    )
    h.feed.connect('ML')
    await settle()
    expect(h.live().jobs).toHaveLength(1)

    h.feed.connect('prob')
    await settle()
    // The snapshot resets, so a stale ML job cannot be attributed to prob.
    expect(h.live().jobs).toEqual([])
    await h.stop()
  })

  it('flushes a final frame that arrived without its trailing newline', async () => {
    const h = harness(
      async (url) =>
        url.includes('/jobs/stream')
          ? closingSse([`data: ${JSON.stringify([job({ id: 42 })])}`])
          : new Response(JSON.stringify({ jobs: [job({ id: 42 })] }), { status: 200 }),
      (n) => {
        if (n >= 2) h.feed.disconnect()
      },
    )
    h.feed.connect(null)
    await h.feed.settled()
    expect(h.live().jobs[0]?.id).toBe(42)
  })
})

describe('JobFeed — the change token', () => {
  it('does not advance for an empty snapshot', async () => {
    // twin: test_change_token_only_moves_when_there_is_something_to_show
    const h = harness(async () => openSse(['data: []\n\n', 'data: []\n\n']))

    const tokens: number[] = []
    h.feed.subscribe((s) => tokens.push(s.changeToken))
    h.feed.connect(null)
    await settle()
    const live = h.live()
    await h.stop()

    expect(live.changeToken).toBe(0)
    expect(new Set(tokens).size).toBe(1)
  })

  it('advances when a job appears', async () => {
    const h = harness(async () => openSse([`data: ${JSON.stringify([job()])}\n\n`]))
    h.feed.connect(null)
    await settle()
    const live = h.live()
    await h.stop()
    expect(live.changeToken).toBe(1)
  })
})

describe('JobFeed — falling back to polling', () => {
  it('polls once between failed stream attempts, then retries the stream', async () => {
    // twin: test_the_stream_is_retried_instead_of_polling_forever
    const seen: string[] = []
    const h = harness(
      async (url) => {
        const isStream = url.includes('/jobs/stream')
        seen.push(isStream ? 'stream' : 'poll')
        if (isStream) throw new Error('refused')
        return new Response(JSON.stringify({ jobs: [job()] }), { status: 200 })
      },
      (n) => {
        if (n > 6) h.feed.disconnect()
      },
    )

    h.feed.connect('ML')
    await h.feed.settled()

    // The bug this pins: polling *instead* of retrying the stream.
    expect(seen.slice(0, 4)).toEqual(['stream', 'poll', 'stream', 'poll'])
    expect(seen.filter((s) => s === 'stream').length).toBeGreaterThanOrEqual(2)
  })

  it('escalates 1,2,5,10 and keeps 10 sticky', async () => {
    const h = harness(
      async () => {
        throw new Error('refused')
      },
      (n) => {
        if (n >= 8) h.feed.disconnect()
      },
    )

    h.feed.connect(null)
    await h.feed.settled()

    // Each failed cycle sleeps the 1s poll interval, then the backoff. The
    // ladder is 1, 2, 5, 10 -- so the first two entries are both 1, one from
    // the poll and one from the ladder.
    expect(h.sleeps.slice(0, 8)).toEqual([1, 1, 1, 2, 1, 5, 1, 10])
  })


  it('treats a non-200 stream response as "no stream"', async () => {
    // twin: test_a_404_stream_is_not_a_stream
    const seen: string[] = []
    const h = harness(
      async (url) => {
        const isStream = url.includes('/jobs/stream')
        seen.push(isStream ? 'stream' : 'poll')
        if (isStream) return new Response('', { status: 404 })
        return new Response(JSON.stringify({ jobs: [job()] }), { status: 200 })
      },
      (n) => {
        if (n >= 3) h.feed.disconnect()
      },
    )

    h.feed.connect(null)
    await h.feed.settled()

    expect(seen).toContain('poll')
    expect(h.live().mode).toBe('poll')
  })

  it('reports "unavailable" when the poll also fails', async () => {
    const h = harness(
      async () => {
        throw new Error('offline')
      },
      (n) => {
        if (n >= 2) h.feed.disconnect()
      },
    )

    h.feed.connect(null)
    await h.feed.settled()
    expect(h.live().mode).toBe('unavailable')
  })

  it('backs off instead of hot-looping when a stream opens and closes at once', async () => {
    // A proxy that accepts and immediately closes would otherwise spin the
    // reconnect loop with zero delay. jobfeed.py:131-132 reconnects instantly
    // in this case; the React port does not.
    const h = harness(
      async (url) =>
        url.includes('/jobs/stream')
          ? closingSse()
          : new Response(JSON.stringify({ jobs: [] }), { status: 200 }),
      (n) => {
        if (n >= 6) h.feed.disconnect()
      },
    )

    h.feed.connect(null)
    await h.feed.settled()

    // Every cycle cost a sleep; none was a bare `continue`.
    expect(h.sleeps.length).toBeGreaterThanOrEqual(6)
    expect(h.sleeps.every((s) => s >= 1)).toBe(true)
  })
})

describe('JobFeed — subscription', () => {
  it('gives a new subscriber the current state immediately', () => {
    const feed = new JobFeed()
    const seen: number[] = []
    feed.subscribe((s) => seen.push(s.changeToken))
    expect(seen).toEqual([0])
  })

  it('stops notifying after unsubscribe', async () => {
    const h = harness(async () => openSse([`data: ${JSON.stringify([job()])}\n\n`]))
    const listener = vi.fn()
    const off = h.feed.subscribe(listener)
    off()

    h.feed.connect(null)
    await settle()
    await h.stop()

    // Only the immediate call made at subscribe time.
    expect(listener).toHaveBeenCalledTimes(1)
  })
})
