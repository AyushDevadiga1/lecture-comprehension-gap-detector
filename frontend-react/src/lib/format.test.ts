import { describe, expect, it } from 'vitest'
import { formatClipTime } from './format'

/**
 * Clip timestamps are offsets into a lecture, in seconds, and they arrive from
 * ffmpeg as floats or as nothing at all. The formatter is the only place that
 * decides what a person reads, so the edges are pinned here rather than left to
 * whatever `Number.prototype.toString` happens to produce.
 */
describe('formatClipTime', () => {
  it('renders m:ss below an hour', () => {
    expect(formatClipTime(0)).toBe('0:00')
    expect(formatClipTime(6)).toBe('0:06')
    expect(formatClipTime(59)).toBe('0:59')
    expect(formatClipTime(60)).toBe('1:00')
    expect(formatClipTime(605)).toBe('10:05')
  })

  it('switches to h:mm:ss past an hour', () => {
    expect(formatClipTime(3600)).toBe('1:00:00')
    expect(formatClipTime(3661)).toBe('1:01:01')
    expect(formatClipTime(7325)).toBe('2:02:05')
  })

  it('truncates fractional seconds rather than rounding them', () => {
    // Rounding 59.6 up to 1:00 would place a clip's start after its end.
    expect(formatClipTime(59.6)).toBe('0:59')
    expect(formatClipTime(0.9)).toBe('0:00')
    expect(formatClipTime(119.999)).toBe('1:59')
  })

  it('clamps negatives to zero', () => {
    // A negative offset means a broken row, but `0:00` is a better thing to
    // render than `-1:-3`.
    expect(formatClipTime(-5)).toBe('0:00')
  })

  it('renders a placeholder for a missing or nonsensical timestamp', () => {
    // A clip whose ffmpeg cut failed has no recorded times. `NaN:NaN` reads as
    // a bug in the app; `--:--` reads as "this clip has no timing", which is
    // what is true.
    expect(formatClipTime(null)).toBe('--:--')
    expect(formatClipTime(undefined)).toBe('--:--')
    expect(formatClipTime(Number.NaN)).toBe('--:--')
    expect(formatClipTime(Number.POSITIVE_INFINITY)).toBe('--:--')
  })
})
