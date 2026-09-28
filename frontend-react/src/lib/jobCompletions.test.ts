import { describe, expect, it } from 'vitest'
import { diffCompletions, isTerminal, stoppedLabel, toAnnouncement } from './jobCompletions'
import { useCompletionStore } from '../store/useCompletionStore'
import type { JobOut } from '../api/types'

/**
 * REACT_ARCHITECTURE.md §1: a terminal job leaves the live view after one
 * render. The Python twin of "record, then announce once" is
 * `shell.py:586-620` (`_record_ready` / `drain_ready`), whose tests live in
 * `tests/test_c4_job_cards.py`.
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

describe('isTerminal', () => {
  it('accepts the flag and every terminal status word', () => {
    expect(isTerminal(job({ terminal: true }))).toBe(true)
    for (const status of ['ready', 'error', 'orphaned', 'cancelled'] as const) {
      expect(isTerminal(job({ status, terminal: false }))).toBe(true)
    }
  })

  it('is false for in-flight work', () => {
    for (const status of ['queued', 'running'] as const) {
      expect(isTerminal(job({ status }))).toBe(false)
    }
  })
})

describe('diffCompletions', () => {
  it('reports nothing when nothing changed', () => {
    const jobs = [job()]
    expect(diffCompletions(jobs, jobs)).toEqual([])
  })

  it('reports a job on the transition into a terminal state', () => {
    const finished = diffCompletions([job()], [job({ status: 'ready', terminal: true })])
    expect(finished).toHaveLength(1)
    expect(finished[0]!.id).toBe(1)
  })

  it('does not re-report a terminal job the feed keeps re-sending', () => {
    // The feed sends a full-array snapshot and keeps the row, so the same
    // terminal job arrives on every tick. This is the "once" guarantee.
    const done = [job({ status: 'ready', terminal: true })]
    expect(diffCompletions(done, done)).toEqual([])
    expect(diffCompletions(done, [job({ id: 2, status: 'running' }), ...done])).toEqual([])
  })

  it('reports a job that first appears already finished', () => {
    // A page opened after the job completed: the first snapshot has it terminal
    // and there is no prior state, so it is genuinely new to this client.
    const finished = diffCompletions([], [job({ status: 'ready', terminal: true })])
    expect(finished).toHaveLength(1)
  })

  it('reports several completions from one snapshot, in feed order', () => {
    const finished = diffCompletions(
      [job({ id: 1 }), job({ id: 2 })],
      [
        job({ id: 1, status: 'ready', terminal: true }),
        job({ id: 2, status: 'error', terminal: true }),
        job({ id: 3, status: 'running' }),
      ],
    )
    expect(finished.map((j) => j.id)).toEqual([1, 2])
  })

  it('does not report a job that went backwards out of terminal', () => {
    // Defensive: a status flap must not produce a second announcement.
    const out = diffCompletions([job({ status: 'ready', terminal: true })], [job()])
    expect(out).toEqual([])
  })
})

describe('toAnnouncement', () => {
  it('uses the backend detail when present', () => {
    expect(toAnnouncement(job({ status: 'ready', detail: 'Clips cut — 28/28 ok' })).detail).toBe(
      'Clips cut — 28/28 ok',
    )
  })

  it("falls back to the Streamlit engine's wording when detail is empty", () => {
    // shell.py:595 -- `detail or f"{title} — Done."`
    const a = toAnnouncement(job({ status: 'ready', detail: '', title: 'Extract concepts' }))
    expect(a.detail).toBe('Extract concepts — Done.')
  })

  it('sets the clips follow-up only for a clips job', () => {
    expect(toAnnouncement(job({ kind: 'clips' })).after).toBe('clips_list')
    expect(toAnnouncement(job({ kind: 'transcribe' })).after).toBeNull()
  })

  it('marks orphaned and cancelled as stopped rather than failed', () => {
    expect(toAnnouncement(job({ status: 'orphaned' })).wasStopped).toBe(true)
    expect(toAnnouncement(job({ status: 'cancelled' })).wasStopped).toBe(true)
    expect(toAnnouncement(job({ status: 'error' })).wasStopped).toBe(false)
  })
})

describe('stoppedLabel', () => {
  it('relabels the raw slugs the Streamlit panel shows', () => {
    // shell.py:465-467
    expect(stoppedLabel('orphaned')).toBe('stopped by a server restart')
    expect(stoppedLabel('cancelled')).toBe('cancelled')
    expect(stoppedLabel('error')).toBe('error')
  })
})

describe('useCompletionStore', () => {
  it('starts empty', () => {
    useCompletionStore.getState().clear()
    expect(useCompletionStore.getState().items).toEqual([])
  })

  it('pushes an announcement', () => {
    useCompletionStore.getState().clear()
    useCompletionStore.getState().push([toAnnouncement(job({ status: 'ready', terminal: true }))])
    expect(useCompletionStore.getState().items).toHaveLength(1)
    expect(useCompletionStore.getState().items[0]!.id).toBe('job-1')
  })

  it('replaces rather than stacks a re-announcement of the same job', () => {
    useCompletionStore.getState().clear()
    const a = toAnnouncement(job({ status: 'ready', terminal: true }))
    useCompletionStore.getState().push([a])
    useCompletionStore.getState().push([a])
    useCompletionStore.getState().push([a])
    expect(useCompletionStore.getState().items).toHaveLength(1)
  })

  it('keeps announcements for different jobs side by side', () => {
    useCompletionStore.getState().clear()
    useCompletionStore.getState().push([
      toAnnouncement(job({ id: 1, status: 'ready', terminal: true })),
      toAnnouncement(job({ id: 2, status: 'ready', terminal: true })),
    ])
    expect(useCompletionStore.getState().items.map((i) => i.jobId)).toEqual([1, 2])
  })

  it('ignores an empty push', () => {
    useCompletionStore.getState().clear()
    useCompletionStore.getState().push([toAnnouncement(job({ id: 1, status: 'ready', terminal: true }))])
    useCompletionStore.getState().push([])
    expect(useCompletionStore.getState().items).toHaveLength(1)
  })

  it('dismisses by id', () => {
    useCompletionStore.getState().clear()
    useCompletionStore.getState().push([
      toAnnouncement(job({ id: 1, status: 'ready', terminal: true })),
      toAnnouncement(job({ id: 2, status: 'ready', terminal: true })),
    ])
    useCompletionStore.getState().dismiss('job-1')
    expect(useCompletionStore.getState().items.map((i) => i.id)).toEqual(['job-2'])
  })
})
