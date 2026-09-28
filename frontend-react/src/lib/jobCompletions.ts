/**
 * Completion detection: which jobs just reached a terminal state.
 *
 * The invariant, from REACT_ARCHITECTURE.md §1: a job reaching
 * `ready | error | orphaned | cancelled` is "removed from the *live* view after
 * one render, exactly as `drain_ready` does in `frontend/panels/shell.py`".
 *
 * The SSE feed sends a **full-array snapshot**, not a diff, and keeps sending it
 * for as long as the job row exists. So "a job finished" cannot be inferred from
 * the presence of a terminal job — it has to be the *transition* into one. That
 * is what this module computes, and it is pure so it can be tested without a
 * feed, a store, or a component.
 *
 * Why this lives in the data layer rather than a component: a component that
 * diffed the job list would have to subscribe to it, and therefore re-render on
 * every 1 Hz snapshot — the very defect §1 exists to remove. Detecting
 * completions at the point the snapshot is written costs zero renders.
 */

import type { JobOut } from '../api/types'

/** Follow-up a finished job should trigger, mirroring the `after` field in
 * `shell.py:_record_ready`. `clips_list` is the one the Streamlit engine sets
 * (`panels/ingest.py:134`). */
export type AfterHook = 'clips_list'

export interface JobAnnouncement {
  jobId: number
  lectureId: number | null
  courseId: string | null
  title: string
  kind: string
  status: string
  /** The backend's own completion text, or the Streamlit fallback. */
  detail: string
  error: string | null
  after: AfterHook | null
  /** True for `orphaned`/`cancelled`, which the Streamlit panel relabels rather
   * than calling a failure. */
  wasStopped: boolean
}

/**
 * A job is finished when the server says it is. The backend sends a boolean
 * `terminal` derived from the same tuple the state machine uses
 * (`backend/api/job_registry.py:30`: `ready, error, orphaned, cancelled`), but
 * the status words are checked too so a payload without the flag still reads
 * correctly.
 *
 * Shared by `diffCompletions` and `useActiveJobs` on purpose: if the two
 * disagreed, a finished job would be announced *and* still shown as live, or a
 * running one would be silently dropped from the drawer.
 */
export const isTerminal = (job: JobOut): boolean =>
  job.terminal === true ||
  job.status === 'ready' ||
  job.status === 'error' ||
  job.status === 'orphaned' ||
  job.status === 'cancelled'

/** Mirrors `shell.py:595`: `detail or f"{title} — Done."` */
const completionDetail = (job: JobOut): string => job.detail || `${job.title ?? 'Job'} — Done.`

/**
 * Terminal jobs present in `next` that were not terminal in `prev`.
 *
 * Order follows `next` (which the backend sorts by id), so announcements appear
 * in a stable order when several jobs finish in the same snapshot.
 */
export function diffCompletions(prev: JobOut[], next: JobOut[]): JobOut[] {
  const wasTerminal = new Map<number, boolean>()
  for (const j of prev) wasTerminal.set(j.id, isTerminal(j))

  const out: JobOut[] = []
  for (const j of next) {
    const now = isTerminal(j)
    if (now && wasTerminal.get(j.id) !== true) out.push(j)
  }
  return out
}

/**
 * Compose the diff with the announcement queue, and report what was announced.
 *
 * This is the whole of "record, then announce once" as a pure function, so the
 * rule can be tested without a feed, a store, or a component — and so the sink
 * in `useJobFeed` has no logic of its own to get wrong.
 */
export function recordNewCompletions(
  prev: JobOut[],
  next: JobOut[],
  push: (announcements: JobAnnouncement[]) => void,
): JobOut[] {
  const finished = diffCompletions(prev, next)
  if (finished.length > 0) push(finished.map(toAnnouncement))
  return finished
}

export function toAnnouncement(job: JobOut): JobAnnouncement {
  return {
    jobId: job.id,
    lectureId: job.lecture_id ?? null,
    courseId: job.course_id ?? null,
    title: job.title ?? `Job #${job.id}`,
    kind: job.kind,
    status: job.status,
    detail: completionDetail(job),
    error: job.error ?? null,
    // The backend does not carry `after`; the client knows which follow-up
    // applies to which job kind. `clips_list` after a clips job is the one the
    // Streamlit engine registers.
    after: job.kind === 'clips' ? 'clips_list' : null,
    wasStopped: job.status === 'orphaned' || job.status === 'cancelled',
  }
}

/** Human label for a job that did not succeed. `shell.py:465-467` relabels
 * `orphaned` as "stopped by a server restart" and `cancelled` as "cancelled"
 * rather than showing the raw slug. */
export function stoppedLabel(status: string): string {
  if (status === 'orphaned') return 'stopped by a server restart'
  if (status === 'cancelled') return 'cancelled'
  return status
}
