/**
 * Is this job stuck, and how long has it been?
 *
 * ## Why a client-side clock is required
 *
 * The Streamlit engine counted *polls*: its progress fragment re-executed every
 * second, so a fingerprint of `status|stage|progress_pct` that did not change
 * could be compared tick by tick (`shell.py:453-458`).
 *
 * The React client has no such tick, and cannot get one for free. The SSE stream
 * emits **only when the serialized snapshot changes** (`backend/api/routes/
 * jobs.py:57-60`). A snapshot carries `heartbeat_at`, which the worker refreshes
 * on every `update_job` — so a healthy job does produce an event about once a
 * second. But a *dead* worker makes no further `update_job` calls, so
 * `heartbeat_at` freezes, the snapshot stops differing, and **the stream goes
 * silent**. A purely reactive stall counter can therefore never fire: the exact
 * condition it exists to detect is the condition that stops the data arriving.
 *
 * So stall state is computed from timestamps against a local clock, and the
 * drawer ticks that clock only while a job is in flight. That is not
 * poll-by-rerender — the page is untouched, and the tick stops the moment no
 * job is running.
 *
 * The other half of C0's fix is preserved: nothing here waits forever. A job
 * that stops moving is called out, and one watched beyond the six-hour backstop
 * is dropped from the live view.
 */

import type { JobOut } from '../api/types'
import { JOB_DEADLINE_S, stallBudgetS } from './stages'

/** The Streamlit fingerprint (`shell.py:453`), kept as a cheap equality check. */
export function progressFingerprint(job: JobOut): string {
  return `${job.status}|${job.stage}|${job.progress_pct}`
}

const parse = (iso: string | null | undefined): number | null => {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

/**
 * The last moment this job demonstrably moved.
 *
 * `heartbeat_at` is the worker's own liveness marker, refreshed on every
 * publish, so it is the right primary signal. `finished_at` only exists once
 * terminal, and `started_at` covers the queued -> running gap. `created_at` is
 * the floor for a job that never started.
 */
export function lastProgressAt(job: JobOut): number {
  const stamps = [parse(job.heartbeat_at), parse(job.finished_at), parse(job.started_at), parse(job.created_at)]
  const known = stamps.filter((t): t is number => t !== null)
  return known.length ? Math.max(...known) : Date.now()
}

/** Seconds since the job last moved, clamped at 0 for clock skew. */
export function secondsSinceProgress(job: JobOut, nowMs: number): number {
  return Math.max(0, (nowMs - lastProgressAt(job)) / 1000)
}

export type JobHealth = 'running' | 'stalled' | 'expired'

export interface StallState {
  health: JobHealth
  /** Seconds since the job last reported progress. */
  sinceProgressS: number
  /** The budget it was measured against. */
  budgetS: number
  /** Wall-clock seconds since the job started, for the deadline. */
  elapsedS: number
}

/**
 * Classify a job at `nowMs`.
 *
 * `expired` is the six-hour backstop from `shell.py:487-493`: watched for an
 * absurd length of time, so stop showing it. The work still runs server-side —
 * the message says so.
 */
export function jobHealth(job: JobOut, nowMs: number): StallState {
  const sinceProgressS = secondsSinceProgress(job, nowMs)
  const budgetS = stallBudgetS(job.stage)
  const started = parse(job.started_at) ?? parse(job.created_at) ?? nowMs
  const elapsedS = Math.max(0, (nowMs - started) / 1000)

  if (elapsedS >= JOB_DEADLINE_S) {
    return { health: 'expired', sinceProgressS, budgetS, elapsedS }
  }
  if (sinceProgressS >= budgetS) {
    return { health: 'stalled', sinceProgressS, budgetS, elapsedS }
  }
  return { health: 'running', sinceProgressS, budgetS, elapsedS }
}

/** `shell.py:462-464`, ported. */
export const STALLED_MESSAGE =
  "Stalled with no progress for a while — the job may have stopped. " +
  'Reload to re-attach.'

/** `shell.py:489-491`, ported. The work is still running server-side. */
export const EXPIRED_MESSAGE =
  'Timed out waiting — the job still runs in the background; reload to re-attach.'

/**
 * Jobs that should appear in the live view.
 *
 * A terminal job is already out (`useActiveJobs`); an `expired` one is dropped
 * too, which is what stops a six-hour spinner.
 */
export function isLive(job: JobOut, nowMs: number): boolean {
  return jobHealth(job, nowMs).health !== 'expired'
}
