import { describe, expect, it } from 'vitest'
import { findDuplicate, splitStalled } from './lectureTriage'
import type { LectureOut } from '../api/types'

/**
 * Ports of the Streamlit triage contracts (`ingest.duplicate_lecture`,
 * `library.stalled_rows`): same cases, same answers. If the Python and this
 * file ever disagree on a row, one of them misclassifies a lecture — and a
 * misclassified row either blocks a resumable upload or deletes real media.
 */

const lec = (over: Partial<LectureOut> & { id: number }): LectureOut => ({
  course_id: 'ml',
  title: 'Lecture',
  status: 'ready',
  created_at: '2026-01-01',
  has_media: true,
  ...over,
})

describe('findDuplicate', () => {
  const rows = [
    lec({ id: 1, title: 'Linear Regression' }),
    lec({ id: 2, title: 'Vectors', course_id: 'prob' }),
  ]

  it('matches a file stem against a lecture title', () => {
    expect(findDuplicate(rows, 'ml', 'linear regression.mp4')).toBe(1)
  })

  it('matches a full filename against a title', () => {
    expect(findDuplicate(rows, 'ml', 'Linear Regression')).toBe(1)
  })

  it('ignores other courses', () => {
    expect(findDuplicate(rows, 'ml', 'vectors.mp4')).toBeNull()
    expect(findDuplicate(rows, 'prob', 'vectors.mp4')).toBe(2)
  })

  it('returns null for empty input', () => {
    expect(findDuplicate(rows, 'ml', null)).toBeNull()
    expect(findDuplicate(rows, 'ml', '')).toBeNull()
    expect(findDuplicate([], 'ml', 'x.mp4')).toBeNull()
    expect(findDuplicate(null, 'ml', 'x.mp4')).toBeNull()
  })

  it('strips only the last extension, like Path.stem', () => {
    expect(findDuplicate([lec({ id: 3, title: 'lecture.tar' })], 'ml', 'lecture.tar.gz')).toBe(3)
  })
})

describe('splitStalled', () => {
  it('sends media-backed rows to resumable and file-less rows to abandoned', () => {
    const rows = [
      lec({ id: 1, status: 'uploaded', has_media: true }),
      lec({ id: 2, status: 'uploaded', has_media: false }),
      lec({ id: 3, status: 'error', has_media: true }),
      lec({ id: 4, status: 'error', has_media: false }),
    ]
    const { resumable, abandoned } = splitStalled(rows, 'ml')
    expect(resumable.map((l) => l.id)).toEqual([1, 3])
    expect(abandoned.map((l) => l.id)).toEqual([2, 4])
  })

  it('ignores healthy rows and other courses', () => {
    const rows = [
      lec({ id: 1, status: 'ready', has_media: true }),
      lec({ id: 2, status: 'transcribing', has_media: true }),
      lec({ id: 3, status: 'uploaded', has_media: true, course_id: 'prob' }),
    ]
    expect(splitStalled(rows, 'ml')).toEqual({ resumable: [], abandoned: [] })
  })

  it('tolerates null input', () => {
    expect(splitStalled(null, 'ml')).toEqual({ resumable: [], abandoned: [] })
  })
})
