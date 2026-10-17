import type { LectureOut } from '../api/types'

/**
 * Lecture-row triage — pure helpers behind the student dashboard's upload
 * guard and stalled-row section. Ported from `frontend/panels/ingest.py`
 * (`duplicate_lecture`) and `frontend/panels/library.py` (`stalled_rows`).
 *
 * Both answer "what is wrong with this row" without touching the network, so
 * they are unit-tested here rather than through the UI.
 */

/** `Lecture 1.mp4` -> `lecture 1`: basename, last extension only, lowered. */
function stem(filename: string): string {
  const base = filename.split(/[\\/]/).pop() ?? filename
  const dot = base.lastIndexOf('.')
  return (dot > 0 ? base.slice(0, dot) : base).toLowerCase()
}

/**
 * Id of an existing lecture in the course that looks like this upload, or
 * null. Two-clause OR, exactly like the Python: the file stem matches a
 * lecture title, or the full filename does (`Path.stem` strips only the last
 * extension, so `lecture.tar.gz` stems to `lecture.tar` — same here).
 */
export function findDuplicate(
  lectures: readonly LectureOut[] | null | undefined,
  courseId: string,
  filename: string | null | undefined,
): number | null {
  if (!filename) return null
  const want = filename.toLowerCase()
  const wantStem = stem(filename)
  for (const lec of lectures ?? []) {
    if (lec.course_id !== courseId) continue
    const title = (lec.title ?? '').toLowerCase()
    if (title === wantStem || want === title) return lec.id
  }
  return null
}

export interface StalledSplit {
  /** Media on disk, transcription never started — fixable with a rerun. */
  resumable: LectureOut[]
  /** No file ever arrived — nothing to resume, clutter to delete. */
  abandoned: LectureOut[]
}

/**
 * Split unfinished rows by what is actually wrong with them. Both surface as
 * `uploaded` (or `error`), but need opposite actions — which is why they must
 * never share one list or one button.
 */
export function splitStalled(
  lectures: readonly LectureOut[] | null | undefined,
  courseId: string,
): StalledSplit {
  const resumable: LectureOut[] = []
  const abandoned: LectureOut[] = []
  for (const lec of lectures ?? []) {
    if (lec.course_id !== courseId) continue
    if (lec.status !== 'uploaded' && lec.status !== 'error') continue
    if (lec.has_media) resumable.push(lec)
    else abandoned.push(lec)
  }
  return { resumable, abandoned }
}
