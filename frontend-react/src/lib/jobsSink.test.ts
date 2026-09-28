import { describe, expect, it, vi } from 'vitest'
import { createJobsSink } from './jobsSink'
import type { Scheduler } from './jobsSink'
import type { FeedState } from './jobFeed'

/**
 * OPEN decision #1 from REACT_ARCHITECTURE.md §11: the coalescing budget for
 * job bursts. These pin the behaviour that "one flush per frame" must have.
 */

const state = (changeToken: number): FeedState => ({
  jobs: [{ id: changeToken } as FeedState['jobs'][number]],
  mode: 'stream',
  changeToken,
})

/** A scheduler that never runs, so a test can inspect the pending write. */
function manualSchedule() {
  const queued: Array<() => void> = []
  const cancel = vi.fn()
  const schedule: Scheduler = (cb) => {
    queued.push(cb)
    return cancel
  }
  return {
    schedule,
    cancel,
    run: () => {
      const cb = queued.pop()
      cb?.()
    },
    get pending() {
      return queued.length
    },
  }
}

describe('createJobsSink', () => {
  it('coalesces many writes in one frame into a single apply', () => {
    const apply = vi.fn()
    const m = manualSchedule()
    const sink = createJobsSink(apply, m.schedule)

    sink.write(state(1))
    sink.write(state(2))
    sink.write(state(3))
    expect(apply).not.toHaveBeenCalled()

    m.run()
    // One apply, carrying only the newest snapshot.
    expect(apply).toHaveBeenCalledTimes(1)
    expect((apply.mock.calls[0]![0] as FeedState).changeToken).toBe(3)
  })

  it('schedules exactly one frame for a burst', () => {
    const m = manualSchedule()
    const sink = createJobsSink(vi.fn(), m.schedule)
    sink.write(state(1))
    sink.write(state(2))
    sink.write(state(3))
    expect(m.pending).toBe(1)
  })

  it('schedules a new frame for the next burst', () => {
    const m = manualSchedule()
    const sink = createJobsSink(vi.fn(), m.schedule)
    sink.write(state(1))
    m.run()
    expect(m.pending).toBe(0)

    sink.write(state(2))
    expect(m.pending).toBe(1)
  })

  it('flush applies the pending snapshot without waiting for the frame', () => {
    const apply = vi.fn()
    const m = manualSchedule()
    const sink = createJobsSink(apply, m.schedule)
    sink.write(state(7))
    sink.flush()
    expect((apply.mock.calls[0]![0] as FeedState).changeToken).toBe(7)
  })

  it('flush is a no-op when nothing is pending', () => {
    const apply = vi.fn()
    const sink = createJobsSink(apply, manualSchedule().schedule)
    sink.flush()
    expect(apply).not.toHaveBeenCalled()
  })

  it('dispose drops the pending snapshot and releases the frame', () => {
    const apply = vi.fn()
    const m = manualSchedule()
    const sink = createJobsSink(apply, m.schedule)
    sink.write(state(1))
    sink.dispose()

    expect(m.cancel).toHaveBeenCalled()
    m.run() // the frame was cancelled, but even if it fired there is nothing to apply
    expect(apply).not.toHaveBeenCalled()
  })
})
