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

export interface UsageRow {
  /** Service id as the backend reports it: `groq.chat`, `local`, … */
  name: string
  detail: string
}

/** How a service id reads to a person. */
const LABELS: Record<string, string> = {
  'groq.chat': 'Groq chat',
  'groq.whisper': 'Groq whisper',
  local: 'Local Whisper',
  ollama: 'Ollama',
}

/**
 * Per-service detail, for the places that show a table rather than one line
 * (Overview's quota card, System & quota). The same three distinctions as
 * `usageLine` — counters, never-called, unlimited-local — because a table is a
 * wider view of the same facts, and the two must not disagree.
 */
export function usageRows(data: UsageOut | null | undefined): UsageRow[] {
  if (!data || !data.services) return []

  const rows: UsageRow[] = []
  for (const [id, svc] of Object.entries(data.services)) {
    const parts: string[] = []

    if (typeof svc.remaining_requests === 'number') {
      parts.push(`${group(svc.remaining_requests)} requests left`)
    }
    if (typeof svc.remaining_tokens === 'number') {
      parts.push(`${group(svc.remaining_tokens)} tokens left`)
    }
    if (typeof svc.reset_in_s === 'number' && svc.reset_in_s > 0) {
      parts.push(`resets in ${Math.floor(svc.reset_in_s / 60)}m`)
    }
    if (svc.available) parts.push('offline · unlimited')
    if (svc.ffmpeg_ok === false) parts.push('ffmpeg missing')
    if (svc.reachable) parts.push('reachable')

    // A service with nothing to say is omitted rather than rendered as a row of
    // dashes: "no data yet" is ambient, and an empty row implies a failure.
    if (parts.length === 0) continue
    rows.push({ name: LABELS[id] ?? id, detail: parts.join(' · ') })
  }
  return rows
}
