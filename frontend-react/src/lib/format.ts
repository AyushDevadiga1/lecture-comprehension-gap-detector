/**
 * Small shared formatters.
 *
 * Separate from the components that use them, and not only for tidiness:
 * `react-refresh/only-export-components` rejects a module that exports both a
 * component and a plain function, because Fast Refresh cannot hot-reload such a
 * module correctly. A helper exported next to a component silently costs you
 * hot reload for that file.
 */

/**
 * `m:ss`, or `h:mm:ss` past an hour, from a count of seconds.
 *
 * Clip ranges are offsets into a lecture, which is why the hour form exists —
 * a 40-minute lecture's last clip is well past an hour of source time once the
 * timeline is measured from zero.
 *
 * Renders `--:--` for null/undefined/NaN rather than `NaN:NaN`, because a clip
 * whose ffmpeg cut never recorded timestamps is a real state (the row exists
 * with `ok = 0`) and showing `NaN:NaN` reads as a bug in the app rather than a
 * clip that failed.
 */
export function formatClipTime(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '--:--'
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = h > 0 ? String(m).padStart(2, '0') : String(m)
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/**
 * Wall-clock duration for a job row — `35s`, `4m 12s`, `1m 03s`.
 *
 * A clock, not a media position: seconds always carry a unit and minutes are
 * padded the way the job registry prints them, so a column of durations lines
 * up. Returns `—` when neither a start nor a finish is known, the same honest
 * placeholder `formatClipTime` uses.
 */
export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`
  return `${s}s`
}
