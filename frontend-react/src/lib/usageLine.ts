import type { UsageOut } from '../api/types'

/**
 * The sidebar's one-line quota summary — pure, so it is testable without a
 * browser or a backend.
 *
 * The rule it follows is the one the backend already established in
 * `frontend/panels/shell.py::_usage_summary`: *say what is known, never invent a
 * number*. Three distinctions matter and each has its own sentence:
 *
 *   - a service with counters → show the counters;
 *   - a service configured but never called → "no usage data yet", which is not
 *     the same claim as "0 left";
 *   - local Whisper → "unlimited", because a quota is meaningless there.
 *
 * Grouping is done by hand rather than `toLocaleString()` so the output is
 * identical on every machine and locale — the test pins the exact string.
 */

/** 4812 -> "4,812". Deterministic, unlike toLocaleString(). */
function group(n: number): string {
  const whole = Math.trunc(Math.abs(n)).toString()
  const withMarks = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return n < 0 ? `-${withMarks}` : withMarks
}

export function usageLine(data: UsageOut | null | undefined): string | null {
  if (!data || !data.services) return null

  const chat = data.services['groq.chat'] ?? {}
  const whisper = data.services['groq.whisper'] ?? {}
  const local = data.services['local'] ?? {}
  const ollama = data.services['ollama'] ?? {}
  const parts: string[] = []

  if (typeof chat.remaining_requests === 'number') {
    parts.push(`Groq ${group(chat.remaining_requests)} req`)
  }
  if (typeof whisper.remaining_requests === 'number') {
    parts.push(`${group(whisper.remaining_requests)} whisper`)
  }
  if (typeof chat.reset_in_s === 'number' && chat.reset_in_s > 0) {
    parts.push(`resets ${Math.floor(chat.reset_in_s / 60)}m`)
  }

  // Nothing metered: describe what can still do the work.
  if (parts.length === 0) {
    if (local.available) return 'Local Whisper · unlimited'
    if (ollama.reachable) return 'Ollama · reachable'
    return null
  }

  // Local Whisper is worth knowing about even alongside a live quota: it is the
  // fallback when Groq runs out, and the ffmpeg flag is what makes it usable.
  if (local.available && local.ffmpeg_ok === false) {
    parts.push('local needs ffmpeg')
  }

  return parts.join(' · ')
}
