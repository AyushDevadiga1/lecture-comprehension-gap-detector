/**
 * Coalesce job snapshots into at most one cache write per animation frame.
 *
 * This is OPEN decision #1 from REACT_ARCHITECTURE.md §11: "Event coalescing
 * budget for job bursts (frame vs microtask vs raw)", with the note "Decide
 * with a measured trace, not a guess."
 *
 * **The measurement.** `backend/api/routes/jobs.py` emits a *full-array*
 * snapshot and only when the serialized snapshot changed since the last poll
 * (`routes/jobs.py:57-60`), at `interval_s` (default 1.0s). So twelve jobs
 * starting together arrive as **one** event carrying twelve rows, not twelve
 * events. The burst case the decision worried about does not arise from this
 * backend at all; the per-frame ceiling is insurance for a multi-course
 * dashboard, not a fix for observed behaviour.
 *
 * A frame is therefore the right budget, and the cheap one: `requestAnimationFrame`
 * is exactly the "don't re-render more than once per painted frame" guarantee we
 * want, and it costs one `setQueryData` per frame in the worst case.
 *
 * `schedule` is injectable so the behaviour is testable without real frames.
 */

export interface JobsSink {
  /** Offer a snapshot. May be deferred to the next frame. */
  write(state: unknown): void
  /** Apply any pending snapshot now. */
  flush(): void
  /** Drop any pending snapshot and release the scheduled frame. */
  dispose(): void
}

export type Scheduler = (cb: () => void) => () => void

/** requestAnimationFrame where available, a timeout otherwise. */
export const frameScheduler: Scheduler = (cb) => {
  if (typeof requestAnimationFrame === 'function') {
    const id = requestAnimationFrame(cb)
    return () => cancelAnimationFrame(id)
  }
  const id = setTimeout(cb, 16)
  return () => clearTimeout(id)
}

export function createJobsSink(
  apply: (state: unknown) => void,
  schedule: Scheduler = frameScheduler,
): JobsSink {
  let pending: unknown = null
  let cancel: (() => void) | null = null

  const flush = () => {
    cancel = null
    if (pending === null) return
    const state = pending
    pending = null
    apply(state)
  }

  return {
    write(state) {
      pending = state
      if (!cancel) cancel = schedule(flush)
    },
    flush,
    dispose() {
      cancel?.()
      cancel = null
      pending = null
    },
  }
}
