import { useEffect, useState } from 'react'

/**
 * A clock that ticks only while something is in flight.
 *
 * Needed because a stalled job stops producing SSE events (§ `jobStalls.ts`), so
 * nothing re-renders and no warning can appear without a local tick. Gated on
 * `enabled` so an idle course costs nothing — this is not poll-by-rerender: the
 * page is untouched, and the interval exists only while a job is running.
 */
export function useNow(enabled: boolean, intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!enabled) return
    // Re-sync immediately on becoming enabled; the hook may have been idle for
    // a while, so the first tick should not report a stale "now".
    setNow(Date.now())
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [enabled, intervalMs])

  return now
}
