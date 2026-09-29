/**
 * The job feed — the single SSE subscription to `GET /jobs/stream`.
 *
 * This is the only file in the app that knows `/jobs/stream` exists (§8).
 *
 * ## Why not EventSource
 *
 * `EventSource` has no header API. The backend's API-key middleware
 * (`backend/main.py`) exempts `/health`, `/docs`, `/openapi.json`, `/redoc` and
 * `/media/*` — **not** `/jobs/stream`. So with `LECGAP_API_KEY` set, a bare
 * `EventSource` gets a 401, fires `error`, and never recovers: the drawer shows
 * "Disconnected" forever and no job ever appears. A streaming `fetch` also
 * gives us the read timeout that `EventSource` cannot express.
 *
 * The Python twin this is ported from is `frontend/jobfeed.py`; the policy
 * below is that file's, not an invention:
 *
 *   - `_RECONNECT_BACKOFF_S = (1, 2, 5, 10)`, the last value sticky rather than
 *     a ramp, and a successful stream resets the attempt counter to zero.
 *     Divergence, deliberate: jobfeed.py:141-142 indexes the tuple with the
 *     already-incremented `attempt`, so `BACKOFF[0]` is unreachable and the
 *     ladder actually runs 2, 5, 10, 10. This indexes `attempt - 1`, so all four
 *     values are reachable and the ladder is 1, 2, 5, 10, 10 as written. The
 *     shape — escalate, then hold at 10 — is unchanged.
 *   - **Every failed stream attempt takes exactly one `GET /jobs` reading**
 *     before backing off. Polling *instead* of retrying the stream is the bug
 *     `tests/test_jobfeed.py::test_the_stream_is_retried_instead_of_polling_
 *     forever` exists to prevent.
 *   - `changeToken` only moves when the published list is **non-empty**, so an
 *     idle course is not mistaken for a change.
 *   - Lines that are not `data: ` are skipped: `retry: 2000`, `: keep-alive`,
 *     `event:`. A malformed frame is skipped, never fatal.
 *   - A non-200 response, a dead socket, or a 404 from a backend that predates
 *     `/jobs/stream` all mean "not a stream" — fall back to polling.
 *   - Connect timeout 5s; read timeout 20s (comfortably above the server's
 *     1s keep-alive, or an idle course would look dead).
 */

import { streamHeaders } from '../api/client'
import type { JobOut, JobListOut } from '../api/types'

const BASE = (import.meta.env.VITE_LECGAP_API_URL as string | undefined) ?? ''

/** `_RECONNECT_BACKOFF_S` from jobfeed.py:27-34. */
const RECONNECT_BACKOFF_S = [1, 2, 5, 10] as const
const POLL_INTERVAL_S = 1
const STREAM_INTERVAL_S = 1
const CONNECT_TIMEOUT_S = 5
const READ_TIMEOUT_S = 20
const POLL_TIMEOUT_S = 5

export type FeedMode = 'starting' | 'stream' | 'poll' | 'unavailable'

export interface FeedState {
  /** Latest full snapshot. The server sends a whole array, never a diff. */
  jobs: JobOut[]
  mode: FeedMode
  /**
   * Monotonic marker that advances only when `jobs` became non-empty. Lets a
   * consumer distinguish "changed" from "same snapshot re-delivered", which is
   * what keeps an idle course from re-rendering (the React equivalent of
   * `jobfeed.changed_since(token)`).
   */
  changeToken: number
}

export type FeedListener = (state: FeedState) => void

/** Where snapshots go. The React binding is `createJobsSink` (see jobsSink.ts). */
export type FeedSink = (state: FeedState) => void

/** Seam so tests can drive time and transport without real sockets. */
export interface JobFeedDeps {
  fetchImpl?: typeof fetch
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>
  setTimer?: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>
  clearTimer?: (h: ReturnType<typeof setTimeout>) => void
}

const realSleep = (ms: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    if (signal.aborted) return resolve()
    const t = setTimeout(done, ms * 1000)
    function done() {
      clearTimeout(t)
      signal.removeEventListener('abort', done)
      resolve()
    }
    signal.addEventListener('abort', done)
  })

export class JobFeed {
  private readonly deps: Required<JobFeedDeps>
  private listeners = new Set<FeedListener>()
  private sink: FeedSink | null = null
  private controller: AbortController | null = null
  private loop: Promise<void> | null = null
  private courseId: string | null = null
  private lastChange = 0
  private state: FeedState = { jobs: [], mode: 'starting', changeToken: 0 }

  constructor(deps: JobFeedDeps = {}) {
    this.deps = {
      fetchImpl: deps.fetchImpl ?? ((...a) => fetch(...a)),
      sleep: deps.sleep ?? realSleep,
      setTimer: deps.setTimer ?? ((fn, ms) => setTimeout(fn, ms)),
      clearTimer: deps.clearTimer ?? ((h) => clearTimeout(h)),
    }
  }

  getState(): FeedState {
    return this.state
  }

  subscribe(listener: FeedListener): () => void {
    this.listeners.add(listener)
    listener(this.state)
    return () => this.listeners.delete(listener)
  }

  /**
   * Open the feed for `courseId`, writing snapshots to `sink`.
   *
   * Idempotent for the same course: a second call with an unchanged course
   * updates the sink and returns, so two components asking for the feed produce
   * one connection, not two. A different course (or a different sink) tears the
   * old connection down first.
   */
  connect(courseId?: string | null, sink?: FeedSink): void {
    const next = courseId || null
    if (this.loop && this.courseId === next) {
      // Idempotent for the same course: swap the sink and keep the connection.
      if (sink) this.sink = sink
      return
    }
    // Tear the old connection down BEFORE installing the new sink.
    //
    // `disconnect()` clears `this.sink`, so doing it after the assignment threw
    // the sink away: the feed connected, streamed, parsed and kept every job in
    // its own `state`, and published to nobody. `this.sink?.(...)` in
    // `publish()` was permanently a no-op, so nothing ever reached the React
    // Query cache and the UI sat at "Disconnected" with an empty job list for
    // the life of the page.
    //
    // The 17 tests in jobFeed.test.ts all missed it because they assert through
    // `subscribe()` (the listener path) and connect without a sink. The sink is
    // the only path the app uses.
    //
    // Order also matters for correctness, not just for survival: `disconnect()`
    // publishes an empty 'starting' state, and that must reach the OUTGOING
    // sink so a course change clears the previous course's jobs off screen.
    this.disconnect()
    if (sink) this.sink = sink
    this.courseId = next
    this.controller = new AbortController()
    this.loop = this.run(this.controller.signal)
  }

  disconnect(): void {
    this.controller?.abort()
    this.controller = null
    this.loop = null
    this.courseId = null
    // Publish BEFORE dropping the sink, so a consumer that installed one sees
    // the reset. Nulling first meant `publish` reached the listeners but not the
    // sink, so a course change left the outgoing sink holding the previous
    // course's jobs until the next frame happened to overwrite them.
    this.publish([], 'starting')
    this.sink = null
  }

  /** Resolves when the feed has fully stopped. Test seam. */
  async settled(): Promise<void> {
    await this.loop?.catch(() => undefined)
  }

  // ------------------------------------------------------------------ writes

  private publish(jobs: JobOut[], mode: FeedMode): void {
    const next = { jobs, mode, changeToken: this.state.changeToken }
    // Mirrors jobfeed.py:118-124 — an empty snapshot is *not* a change.
    if (jobs.length) next.changeToken = ++this.lastChange
    this.state = next
    this.sink?.(next)
    for (const l of this.listeners) l(next)
  }

  // ------------------------------------------------------------------- loops

  private async run(signal: AbortSignal): Promise<void> {
    let attempt = 0
    while (!signal.aborted) {
      const outcome = await this.streamOnce(signal)
      if (outcome === 'ran') attempt = 0
      if (signal.aborted) return
      // Take exactly one cheap reading so the UI still updates, then back off and
      // try the stream again. This runs on the failure path *and* when a stream
      // that opened cleanly then ended -- reconnecting instantly in that case is
      // a hot loop, which is what jobfeed.py:131-132 would do against a proxy
      // that accepts and immediately closes.
      await this.pollOnce(signal)
      if (signal.aborted) return
      attempt += 1
      const idx = Math.min(attempt - 1, RECONNECT_BACKOFF_S.length - 1)
      await this.deps.sleep(RECONNECT_BACKOFF_S[idx]!, signal)
    }
  }

  /**
   * One SSE connection.
   *
   * `ran`     the stream opened and delivered at least a connection.
   * `ended`   the stream opened, then the server closed it.
   * `failed`  it never opened (offline, 401, 404, refused).
   */
  private async streamOnce(signal: AbortSignal): Promise<'ran' | 'ended' | 'failed'> {
    const url = new URL(`${BASE}/jobs/stream`, window.location.origin)
    url.searchParams.set('interval_s', String(STREAM_INTERVAL_S))
    if (this.courseId) url.searchParams.set('course_id', this.courseId)

    let res: Response
    const connectAbort = new AbortController()
    const connectTimer = this.deps.setTimer(
      () => connectAbort.abort(),
      CONNECT_TIMEOUT_S * 1000,
    )
    const onAbort = () => connectAbort.abort()
    signal.addEventListener('abort', onAbort)
    try {
      res = await this.deps.fetchImpl(url.toString(), {
        headers: streamHeaders(),
        signal: connectAbort.signal,
      })
    } catch {
      return 'failed'
    } finally {
      this.deps.clearTimer(connectTimer)
      signal.removeEventListener('abort', onAbort)
    }

    if (!res.ok || !res.body) return 'failed'

    this.publish([], 'stream')

    // Read watchdog: the server keep-alives every 1s, so 20s of silence is a
    // dropped socket, not an idle course.
    let readTimer: ReturnType<typeof setTimeout> | null = null
    const armRead = () => {
      if (readTimer) this.deps.clearTimer(readTimer)
      readTimer = this.deps.setTimer(() => connectAbort.abort(), READ_TIMEOUT_S * 1000)
    }
    armRead()
    connectAbort.signal.addEventListener('abort', () => {
      if (readTimer) this.deps.clearTimer(readTimer)
    })

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) {
          // A frame that arrived without its trailing newline would otherwise be
          // stranded in the buffer. The backend always sends "\n\n", so this is
          // belt-and-braces rather than a path it exercises.
          if (buffer) this.handleLine(buffer.replace(/\r$/, ''))
          return 'ended'
        }
        armRead()
        buffer += decoder.decode(value, { stream: true })
        let nl: number
        while ((nl = buffer.indexOf('\n')) !== -1) {
          const line = buffer.slice(0, nl).replace(/\r$/, '')
          buffer = buffer.slice(nl + 1)
          this.handleLine(line)
        }
      }
    } catch {
      return 'ended'
    }
  }

  /** One `GET /jobs` reading — the fallback while the stream is down. */
  private async pollOnce(signal: AbortSignal): Promise<void> {
    const url = new URL(`${BASE}/jobs`, window.location.origin)
    if (this.courseId) url.searchParams.set('course_id', this.courseId)

    // A manual timeout rather than AbortSignal.timeout: the latter is a
    // platform API jsdom does not always provide, and this file is the seam the
    // tests drive.
    const pollAbort = new AbortController()
    const onAbort = () => pollAbort.abort()
    signal.addEventListener('abort', onAbort)
    const timer = this.deps.setTimer(() => pollAbort.abort(), POLL_TIMEOUT_S * 1000)

    try {
      const res = await this.deps.fetchImpl(url.toString(), {
        headers: streamHeaders(),
        signal: pollAbort.signal,
      })
      if (!res.ok) {
        this.publish([], 'unavailable')
      } else {
        const body = (await res.json()) as JobListOut
        this.publish(Array.isArray(body?.jobs) ? body.jobs : [], 'poll')
      }
    } catch {
      this.publish([], 'unavailable')
    } finally {
      this.deps.clearTimer(timer)
      signal.removeEventListener('abort', onAbort)
    }
    await this.deps.sleep(POLL_INTERVAL_S, signal)
  }

  private handleLine(line: string): void {
    if (!line.startsWith('data: ')) return // 'retry:', ': keep-alive', 'event:'
    try {
      const parsed = JSON.parse(line.slice('data: '.length)) as JobOut[]
      if (Array.isArray(parsed)) this.publish(parsed, 'stream')
    } catch {
      // A malformed frame must not kill the feed.
    }
  }
}

/** One feed per tab, shared by every component that asks for it. */
export const jobFeed = new JobFeed()
