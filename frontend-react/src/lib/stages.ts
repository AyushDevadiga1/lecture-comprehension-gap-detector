/**
 * What each pipeline stage is actually doing, in words a student can read.
 *
 * The drawer rendered `job.stage` raw, so a lecturer uploading a 90-minute
 * video saw `building_graph` for four minutes with no idea whether it was
 * working. The `local_transcribing` case is the sharpest: CPU Whisper decodes at
 * roughly real time, so an hour of audio sits at 50% for 45-90 minutes looking
 * frozen. Without that sentence the honest read is "this is broken".
 *
 * Ported verbatim from `_STAGE_HINTS` in `frontend/panels/shell.py:48-70` —
 * including the `clips` / `cutting_clips` alias pair, because the backend emits
 * both (`backend/api/jobs/progress.py:_STAGE_TO_STATUS`).
 */

export const STAGE_HINTS: Record<string, string> = {
  initializing: 'Starting the background job…',
  probing: 'Probing audio duration with ffprobe…',
  downmixing: 'Normalizing audio to 16 kHz mono FLAC…',
  loading_model: 'Whisper model loading (one-time, ~1 min on CPU)…',
  chunking: 'Slicing audio into API-sized chunks…',
  transcribing:
    'Hosted Whisper is transcribing — usually a few minutes for a full lecture.',
  local_transcribing:
    'CPU Whisper decodes at roughly real-time: a 1-hour lecture takes ~45–90 min ' +
    'and this bar stays put until it finishes. Leave the page open; you can ' +
    'refresh anytime to re-attach.',
  finalizing: 'Finalizing timestamps…',
  saving_segments: 'Saving transcript segments to the database…',
  extracting:
    'Reading the lecture structure (passages, concepts, spoken prerequisite links)…',
  building_graph: 'Deduplicating concepts and scoring prerequisite edges…',
  clips:
    'Cutting concept clips with ffmpeg (re-encoded, several minutes for many clips)…',
  cutting_clips:
    'Cutting concept clips with ffmpeg (re-encoded, several minutes for many clips)…',
  saving_clips: 'Saving clip rows…',
}

/**
 * Fallback for a stage with no entry. `shell.py:350`:
 * `f"Currently: {stage or 'working'}."`
 */
export function stageHint(stage: string | null | undefined): string {
  return STAGE_HINTS[stage ?? ''] ?? `Currently: ${stage || 'working'}.`
}

/**
 * The hint plus elapsed time, from `_job_guidance` (`shell.py:349-354`).
 *
 * The two spaces before the parenthesis are in the original and are kept, so
 * this is a faithful port rather than a reworded one.
 */
export function jobGuidance(stage: string | null | undefined, elapsedS: number | null | undefined): string {
  const hint = stageHint(stage)
  const total = Math.floor(elapsedS ?? 0)
  const mm = Math.floor(total / 60)
  const ss = total % 60
  if (mm) return `${hint}  (${mm}m ${String(ss).padStart(2, '0')}s elapsed)`
  return `${hint}  (${ss}s elapsed)`
}

/**
 * Stages that legitimately sit still for a long time. `shell.py:37-39`.
 *
 * Local Whisper and a re-encode are the two: both are long, both look frozen,
 * and penalising them for it would fire the stall warning on healthy work.
 */
export const SLOW_STAGES = new Set([
  'building_graph',
  'extracting',
  'cutting_clips',
  'clips',
  'local_transcribing',
  'loading_model',
  'transcribing',
])

/**
 * How long a stage may report no change before it is called stalled.
 *
 * `shell.py:36,39`: 40s normally, 600s for a slow stage. The Streamlit version
 * counted *polls* (its fragment re-executed every second); here it is measured
 * in seconds since the job last moved, which is the same quantity without
 * tying it to a render cadence — see `jobStalls.ts` for why the client needs
 * its own clock.
 */
export const STALL_BUDGET_S = 40
export const STALL_BUDGET_SLOW_S = 600

/** `shell.py:22` — the six-hour backstop. */
export const JOB_DEADLINE_S = 6 * 60 * 60

/** `shell.py:17` — consecutive unreachable readings tolerated. */
export const MAX_POLL_FAILS = 5

export function stallBudgetS(stage: string | null | undefined): number {
  return SLOW_STAGES.has(stage ?? '') ? STALL_BUDGET_SLOW_S : STALL_BUDGET_S
}
