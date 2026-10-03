import type { FeedMode } from './jobFeed'

/**
 * One honest description of the job feed, for every surface that shows it.
 *
 * ## The failure this exists to end
 *
 * `FeedMode` has four values and two of them were being flattened into
 * "not connected":
 *
 *   - `poll` — the stream is not available, so `jobFeed` fell back to 1 Hz
 *     `GET /jobs` polling. This **works**. Jobs update; progress is live; only
 *     the transport is degraded.
 *   - `unavailable` — every attempt failed and the feed gave up. Nothing will
 *     update, and no amount of waiting will change that.
 *
 * `Navbar` asked `mode === 'stream'` and reported anything else as *"Connecting
 * to SSE Stream…"*, with a warning-coloured dot. `JobDrawer` asked the same
 * question and labelled both `poll` and `unavailable` **"Disconnected"**. So the
 * one state where the feed had genuinely given up was the one state that looked
 * like it was still trying — indefinitely, with no way to tell it apart from a
 * slow start.
 *
 * That is the same mistake the 401 banner was built to stop: a status that reads
 * as *transient* when it is *terminal*, sending the reader off to wait for
 * something that will never arrive.
 *
 * ## Why `tone` and not a colour
 *
 * Three consumers want to paint this — a navbar dot, a drawer chip, a tooltip.
 * Returning a semantic tone rather than a colour keeps the palette rule intact
 * (`theme/alpha.ts`): each surface maps `tone` onto its own slot.
 */

export type FeedTone = 'ok' | 'degraded' | 'down'

export interface FeedStatus {
  /** Short, for a chip. Never longer than two words. */
  label: string
  /** Sentence, for a tooltip. Says what is and is not working. */
  detail: string
  tone: FeedTone
}

const STATUS: Record<FeedMode, FeedStatus> = {
  starting: {
    label: 'Connecting',
    detail: 'Opening the job stream…',
    tone: 'degraded',
  },
  stream: {
    label: 'SSE Live',
    detail: 'Live updates over the event stream.',
    tone: 'ok',
  },
  poll: {
    label: 'Polling',
    // Says *both* halves: the stream is down, and progress is still arriving.
    // Reporting only the first would read as a dead feature.
    detail: 'The event stream is unavailable, so jobs are updating by polling instead.',
    tone: 'degraded',
  },
  unavailable: {
    label: 'Disconnected',
    // The one state that is terminal. Say so, and say what it costs.
    detail: 'The job feed is unreachable. Job progress will not update until it reconnects.',
    tone: 'down',
  },
}

export function feedStatus(mode: FeedMode): FeedStatus {
  return STATUS[mode]
}

/** True only when updates are arriving over the stream itself. */
export function isStreamLive(mode: FeedMode): boolean {
  return mode === 'stream'
}

/**
 * True when the feed is neither streaming nor polling — i.e. nothing is
 * updating and the user should be told, rather than left watching a stale list.
 */
export function isFeedDown(mode: FeedMode): boolean {
  return mode === 'unavailable'
}