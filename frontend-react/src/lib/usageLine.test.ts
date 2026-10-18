import { describe, expect, it } from 'vitest'
import { usageLine, usageRows } from './usageLine'
import type { UsageOut } from '../api/types'

/**
 * The quota line's job is to be honest about three different situations that a
 * naive renderer collapses into one: counters, configured-but-unused, and
 * unlimited-local. Each case is pinned here.
 */

const usage = (services: UsageOut['services'], availability?: Record<string, boolean>): UsageOut => ({
  services,
  availability,
})

describe('usageLine', () => {
  it('renders nothing when there is no usage payload', () => {
    expect(usageLine(null)).toBeNull()
    expect(usageLine(undefined)).toBeNull()
  })

  it('shows the Groq counters, grouped and joined', () => {
    expect(
      usageLine(
        usage({
          'groq.chat': { remaining_requests: 4812, reset_in_s: 720 },
          'groq.whisper': { remaining_requests: 71 },
        }),
      ),
    ).toBe('Groq 4,812 req · 71 whisper · resets 12m')
  })

  it('formats thousands deterministically', () => {
    // Not toLocaleString(): the same string on every machine.
    expect(usageLine(usage({ 'groq.chat': { remaining_requests: 1234567 } }))).toBe(
      'Groq 1,234,567 req',
    )
    expect(usageLine(usage({ 'groq.chat': { remaining_requests: 999 } }))).toBe('Groq 999 req')
  })

  it('says "unlimited" for local Whisper rather than inventing a quota', () => {
    expect(usageLine(usage({ local: { available: true, ffmpeg_ok: true } }))).toBe(
      'Local Whisper · unlimited',
    )
  })

  it('falls back to Ollama when nothing is metered', () => {
    expect(usageLine(usage({ ollama: { reachable: true } }))).toBe('Ollama · reachable')
  })

  it('flags a local backend that cannot actually run without ffmpeg', () => {
    // The fallback is only a fallback if ffmpeg is there to make it work.
    expect(
      usageLine(
        usage({
          'groq.chat': { remaining_requests: 10 },
          local: { available: true, ffmpeg_ok: false },
        }),
      ),
    ).toBe('Groq 10 req · local needs ffmpeg')
  })

  it('returns null when nothing at all is known', () => {
    expect(usageLine(usage({}))).toBeNull()
    // A configured service with no counters yet is also "nothing to say" — the
    // absence of a number must not render as zero.
    expect(usageLine(usage({ 'groq.chat': {} }, { groq_configured: true }))).toBeNull()
  })

  it('ignores a zero reset countdown', () => {
    expect(usageLine(usage({ 'groq.chat': { remaining_requests: 5, reset_in_s: 0 } }))).toBe(
      'Groq 5 req',
    )
  })
})

describe('usageRows', () => {
  it('gives every service a readable name and its own detail', () => {
    expect(
      usageRows(
        usage({
          'groq.chat': { remaining_requests: 4812, remaining_tokens: 1200000, reset_in_s: 720 },
          'groq.whisper': { remaining_requests: 71 },
          local: { available: true, ffmpeg_ok: true },
          ollama: { reachable: true },
        }),
      ),
    ).toEqual([
      { name: 'Groq chat', detail: '4,812 requests left · 1,200,000 tokens left · resets in 12m' },
      { name: 'Groq whisper', detail: '71 requests left' },
      { name: 'Local Whisper', detail: 'offline · unlimited' },
      { name: 'Ollama', detail: 'reachable' },
    ])
  })

  it('omits a service with nothing to report instead of showing dashes', () => {
    expect(usageRows(usage({ 'groq.chat': {} }))).toEqual([])
    expect(usageRows(null)).toEqual([])
  })

  it('flags a local backend whose ffmpeg is missing', () => {
    expect(usageRows(usage({ local: { available: true, ffmpeg_ok: false } }))).toEqual([
      { name: 'Local Whisper', detail: 'offline · unlimited · ffmpeg missing' },
    ])
  })

  it('keeps an unknown service id, labelled as itself', () => {
    // A new backend service must appear, not vanish, before a label exists.
    expect(usageRows(usage({ 'some.new.thing': { remaining_requests: 5 } }))).toEqual([
      { name: 'some.new.thing', detail: '5 requests left' },
    ])
  })
})
