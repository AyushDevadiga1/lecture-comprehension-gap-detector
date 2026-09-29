import { describe, expect, it } from 'vitest'
import {
  jobGuidance,
  stageHint,
  SLOW_STAGES,
  STALL_BUDGET_S,
  STALL_BUDGET_SLOW_S,
  stallBudgetS,
  STAGE_HINTS,
} from './stages'

/**
 * Ported from `_STAGE_HINTS` and `_job_guidance` in `frontend/panels/shell.py`.
 * The Python twins are asserted in `tests/test_c0_fixes.py` and
 * `tests/test_runtime_fixes.py`.
 */

describe('stageHint', () => {
  it('explains the stage a student is most likely to misread', () => {
    // The sharpest case: CPU Whisper is legitimately frozen-looking for an hour.
    expect(stageHint('local_transcribing')).toMatch(/45–90 min/)
    expect(stageHint('local_transcribing')).toMatch(/stays put/)
  })

  it('covers every stage the backend can emit', () => {
    // The stages the worker pipeline publishes, from
    // backend/api/jobs/progress.py and the workers.
    for (const stage of [
      'probing',
      'downmixing',
      'chunking',
      'transcribing',
      'finalizing',
      'saving_segments',
      'extracting',
      'building_graph',
      'clips',
      'saving_clips',
    ]) {
      expect(STAGE_HINTS[stage], `missing hint for ${stage}`).toBeTruthy()
    }
  })

  it('has the same wording for the clips alias pair', () => {
    // The backend emits both slugs for one step.
    expect(STAGE_HINTS.clips).toBe(STAGE_HINTS.cutting_clips)
  })

  it('falls back to the raw slug, as shell.py:350 does', () => {
    expect(stageHint('some_future_stage')).toBe('Currently: some_future_stage.')
    expect(stageHint(null)).toBe('Currently: working.')
    expect(stageHint('')).toBe('Currently: working.')
  })
})

describe('jobGuidance', () => {
  it('formats seconds under a minute', () => {
    expect(jobGuidance('probing', 7)).toBe(`${STAGE_HINTS.probing}  (7s elapsed)`)
  })

  it('formats minutes with a zero-padded seconds field', () => {
    expect(jobGuidance('probing', 60)).toBe(`${STAGE_HINTS.probing}  (1m 00s elapsed)`)
    expect(jobGuidance('probing', 125)).toBe(`${STAGE_HINTS.probing}  (2m 05s elapsed)`)
  })

  it('treats a missing elapsed time as zero', () => {
    expect(jobGuidance('probing', null)).toBe(`${STAGE_HINTS.probing}  (0s elapsed)`)
    expect(jobGuidance('probing', undefined)).toBe(`${STAGE_HINTS.probing}  (0s elapsed)`)
  })

  it('keeps the two spaces before the parenthesis from the original', () => {
    // shell.py:352-354 — `f"{hint}  ({ss}s elapsed)"`, two spaces. Kept so the
    // output is a faithful port rather than a reworded one.
    expect(jobGuidance('probing', 3)).toBe(
      `${STAGE_HINTS.probing}  (3s elapsed)`,
    )
    expect(jobGuidance('probing', 3)).toContain('  (3s elapsed)')
  })
})

describe('stallBudgetS', () => {
  it('is 40s for a normal stage', () => {
    expect(stallBudgetS('probing')).toBe(STALL_BUDGET_S)
    expect(stallBudgetS(null)).toBe(STALL_BUDGET_S)
  })

  it('is 600s for a stage that legitimately sits still', () => {
    // Penalising local Whisper or a re-encode for looking frozen would fire the
    // warning on healthy work.
    for (const stage of SLOW_STAGES) {
      expect(stallBudgetS(stage), stage).toBe(STALL_BUDGET_SLOW_S)
    }
  })

  it('keeps the slow budget far above the fast one and below the deadline', () => {
    // The Python pins this relation: _MAX_STALLED_POLLS_SLOW * 1.5 < _JOB_DEADLINE_S
    expect(STALL_BUDGET_SLOW_S / STALL_BUDGET_S).toBeGreaterThan(1.5)
  })
})
