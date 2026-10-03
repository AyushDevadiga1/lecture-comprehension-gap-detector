import { describe, expect, it } from 'vitest'
import { feedStatus, isFeedDown, isStreamLive } from './feedStatus'
import type { FeedMode } from './jobFeed'

/**
 * The property under test is not "the labels are pretty" — it is that the two
 * degraded states are *distinguishable from each other*, and that the terminal
 * one does not read as transient.
 *
 * `Navbar` used to report `mode === 'stream' ? live : "Connecting to SSE
 * Stream…"` and `JobDrawer` used to report `mode === 'stream' ? 'SSE Live' :
 * 'Disconnected'`. So `poll` (degraded but working) and `unavailable` (given
 * up, will never update) were the same two words, and `unavailable` in the
 * navbar claimed to be mid-connection, forever.
 */

const MODES: FeedMode[] = ['starting', 'stream', 'poll', 'unavailable']

describe('feedStatus', () => {
  it('describes every mode', () => {
    for (const mode of MODES) {
      const s = feedStatus(mode)
      expect(s.label, mode).toBeTruthy()
      expect(s.detail, mode).toBeTruthy()
      expect(['ok', 'degraded', 'down'], mode).toContain(s.tone)
    }
  })

  it('only calls the stream live', () => {
    expect(feedStatus('stream').tone).toBe('ok')
    for (const mode of MODES.filter((m) => m !== 'stream')) {
      expect(feedStatus(mode).tone, mode).not.toBe('ok')
    }
  })

  it('never gives `poll` and `unavailable` the same label', () => {
    // The exact regression: both rendered "Disconnected", so a feed that had
    // given up looked like one that was merely not streaming.
    expect(feedStatus('poll').label).not.toBe(feedStatus('unavailable').label)
    expect(feedStatus('poll').detail).not.toBe(feedStatus('unavailable').detail)
  })

  it('treats `poll` as degraded-but-working, not as down', () => {
    // A user told "Disconnected" stops trusting the progress numbers. Polling
    // is still live data, so the copy has to say so.
    const poll = feedStatus('poll')
    expect(poll.tone).toBe('degraded')
    expect(poll.detail).toMatch(/polling/i)
    expect(isFeedDown('poll')).toBe(false)
  })

  it('treats `unavailable` as terminal and says what it costs', () => {
    const down = feedStatus('unavailable')
    expect(down.tone).toBe('down')
    expect(isFeedDown('unavailable')).toBe(true)
    // Must not read as transient, or the reader waits for something that is
    // never coming.
    expect(down.detail).toMatch(/will not update/i)
    expect(down.detail).not.toMatch(/connecting/i)
  })

  it('gives `starting` a transient description', () => {
    const starting = feedStatus('starting')
    expect(starting.tone).toBe('degraded')
    expect(starting.detail).toMatch(/…|\.\.\./)
    expect(isFeedDown('starting')).toBe(false)
  })

  it('keeps every label to at most two words', () => {
    // The label goes in a Chip. A sentence there wraps the drawer header.
    for (const mode of MODES) {
      expect(feedStatus(mode).label.split(/\s+/).length, mode).toBeLessThanOrEqual(2)
    }
  })

  it('isStreamLive is exactly the stream mode', () => {
    for (const mode of MODES) expect(isStreamLive(mode), mode).toBe(mode === 'stream')
  })
})