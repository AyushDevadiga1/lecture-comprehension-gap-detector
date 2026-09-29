import { describe, expect, it } from 'vitest'
import {
  EXPIRED_MESSAGE,
  isLive,
  jobHealth,
  lastProgressAt,
  progressFingerprint,
  secondsSinceProgress,
  STALLED_MESSAGE,
} from './jobStalls'
import { JOB_DEADLINE_S, STALL_BUDGET_S, STALL_BUDGET_SLOW_S } from './stages'
import type { JobOut } from '../api/types'

/**
 * The half of C0 that lives in the client. The Python twin is
 * `frontend/panels/shell.py:453-493` and its tests are in
 * `tests/test_c0_fixes.py` / `tests/test_runtime_fixes.py`.
 *
 * The important difference, and the reason this is timestamp-based rather than
 * a poll counter: the SSE stream only emits when the serialized snapshot
 * changes, and a snapshot carries `heartbeat_at`. A dead worker stops refreshing
 * it, so **the stream goes silent exactly when a stall begins** — a reactive
 * counter could never fire.
 */

const T0 = 1_700_000_000_000

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
    created_at: new Date(T0).toISOString(),
    started_at: new Date(T0).toISOString(),
    heartbeat_at: new Date(T0).toISOString(),
    terminal: false,
    ...over,
  }) as JobOut

describe('progressFingerprint', () => {
  it('changes when any of the three moving parts changes', () => {
    const a = job()
    expect(progressFingerprint(a)).toBe(progressFingerprint({ ...a }))
    expect(progressFingerprint({ ...a, progress_pct: 41 })).not.toBe(progressFingerprint(a))
    expect(progressFingerprint({ ...a, stage: 'finalizing' })).not.toBe(progressFingerprint(a))
    expect(progressFingerprint({ ...a, status: 'ready' })).not.toBe(progressFingerprint(a))
  })
})

describe('lastProgressAt', () => {
  it('prefers the heartbeat, the worker liveness marker', () => {
    const j = job({
      created_at: new Date(T0).toISOString(),
      started_at: new Date(T0 + 1000).toISOString(),
      heartbeat_at: new Date(T0 + 5000).toISOString(),
    })
    expect(lastProgressAt(j)).toBe(T0 + 5000)
  })

  it('falls back to finished, then started, then created', () => {
    expect(lastProgressAt(job({ heartbeat_at: null, started_at: new Date(T0 + 7).toISOString() }))).toBe(T0 + 7)
    expect(lastProgressAt(job({ heartbeat_at: null, started_at: null }))).toBe(T0)
  })

  it('survives a payload with no timestamps at all', () => {
    const j = job({ heartbeat_at: null, started_at: null, created_at: null })
    expect(Number.isFinite(lastProgressAt(j))).toBe(true)
  })
})

describe('secondsSinceProgress', () => {
  it('measures from the last heartbeat', () => {
    const j = job({ heartbeat_at: new Date(T0).toISOString() })
    expect(secondsSinceProgress(j, T0 + 30_000)).toBeCloseTo(30, 0)
  })

  it('is never negative, even if the clock jumped', () => {
    const j = job({ heartbeat_at: new Date(T0).toISOString() })
    expect(secondsSinceProgress(j, T0 - 5000)).toBe(0)
  })
})

describe('jobHealth', () => {
  it('is running while progress keeps arriving', () => {
    const j = job({ heartbeat_at: new Date(T0).toISOString() })
    expect(jobHealth(j, T0 + 5_000).health).toBe('running')
  })

  it('becomes stalled once a normal stage goes quiet past its budget', () => {
    const j = job({ stage: 'saving_segments', heartbeat_at: new Date(T0).toISOString() })
    const state = jobHealth(j, T0 + (STALL_BUDGET_S + 1) * 1000)
    expect(state.health).toBe('stalled')
    expect(state.budgetS).toBe(STALL_BUDGET_S)
  })

  it('does not call a slow stage stalled for the same duration', () => {
    // The case that would produce a false alarm on healthy work.
    const j = job({ stage: 'local_transcribing', heartbeat_at: new Date(T0).toISOString() })
    expect(jobHealth(j, T0 + (STALL_BUDGET_S + 1) * 1000).health).toBe('running')
    expect(jobHealth(j, T0 + (STALL_BUDGET_SLOW_S + 1) * 1000).health).toBe('stalled')
  })

  it('expires a job watched past the six-hour backstop', () => {
    const j = job({ heartbeat_at: new Date(T0).toISOString() })
    const state = jobHealth(j, T0 + (JOB_DEADLINE_S + 1) * 1000)
    expect(state.health).toBe('expired')
  })

  it('expires even when the stage is a slow one', () => {
    // The deadline is absolute: a long stage must not be exempt from it, or a
    // stalled local transcription would hold a card for six hours.
    const j = job({ stage: 'local_transcribing', heartbeat_at: new Date(T0).toISOString() })
    expect(jobHealth(j, T0 + (JOB_DEADLINE_S + 1) * 1000).health).toBe('expired')
  })

  it('reports elapsed time since the job started', () => {
    const j = job({ heartbeat_at: new Date(T0).toISOString() })
    expect(jobHealth(j, T0 + 90_000).elapsedS).toBeCloseTo(90, 0)
  })
})

describe('isLive', () => {
  it('keeps a healthy job and drops an expired one', () => {
    const j = job({ heartbeat_at: new Date(T0).toISOString() })
    expect(isLive(j, T0 + 1000)).toBe(true)
    expect(isLive(j, T0 + (JOB_DEADLINE_S + 1) * 1000)).toBe(false)
  })
})

describe('the messages say the truth', () => {
  it('a stall warning admits the job may have stopped', () => {
    // shell.py:462-463
    expect(STALLED_MESSAGE).toMatch(/may have stopped/i)
    expect(STALLED_MESSAGE).toMatch(/re-attach/i)
  })

  it('an expiry says the work is still running server-side', () => {
    // shell.py:489-490 — otherwise a reader assumes the work was cancelled.
    expect(EXPIRED_MESSAGE).toMatch(/still runs in the background/i)
  })
})
