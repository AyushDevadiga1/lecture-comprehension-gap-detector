import { describe, expect, it } from 'vitest'
import { buildTheme } from './muiTheme'

/**
 * React-theme shape: the type pairing, and the slider skin.
 *
 * `theme.test.ts` is the port of the Python colour tests — it proves the
 * *palette*. This file proves the two decisions layered on top of it that no
 * colour rule can see: which face carries which job, and that the slider is
 * themed from tokens rather than left to the platform.
 *
 * The weight guard exists because the failure is invisible in review: asking a
 * serif for 700 when only 400–600 are loaded does not error, it silently
 * synthesises faux bold. Every `fontWeight: 800` in the codebase had to be swept
 * when Newsreader landed; without a guard the next one reappears quietly.
 */

const sources = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const DISPLAY_SLOTS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] as const

describe('the type pairing', () => {
  const theme = buildTheme('dark')

  it('puts the editorial serif on every heading slot', () => {
    for (const slot of DISPLAY_SLOTS) {
      expect(theme.typography[slot].fontFamily, slot).toMatch(/Newsreader/)
    }
  })

  it('keeps body text on the neutral sans', () => {
    expect(theme.typography.fontFamily).toMatch(/Plus Jakarta Sans/)
    expect(theme.typography.fontFamily).not.toMatch(/Newsreader/)
    expect(theme.typography.body1.fontFamily ?? theme.typography.fontFamily).not.toMatch(/Newsreader/)
  })

  it('never asks the display face for a weight it does not have', () => {
    // Newsreader ships 400/500/600. Anything heavier is synthesised.
    for (const slot of DISPLAY_SLOTS) {
      const weight = theme.typography[slot].fontWeight as number
      expect(weight, `${slot} weight`).toBeLessThanOrEqual(600)
    }
  })

  it('the guard can actually see a violation', () => {
    // Positive control: if the check above silently stopped matching, this
    // fails instead of the suite passing for the wrong reason.
    const bad = { h1: { fontFamily: "'Newsreader', serif", fontWeight: 800 } }
    expect(bad.h1.fontWeight).toBeGreaterThan(600)
  })
})

describe('no module synthesises bold on the display face', () => {
  const files = Object.entries(sources).filter(([k]) => !k.includes('.test.'))
  const WEIGHT_800 = /fontWeight:\s*['"]?800/

  /**
   * Comments are stripped before matching, deliberately: the natural way to
   * document this rule is to name the value it forbids, and a guard that fails
   * on its own documentation is a guard that gets deleted. (First run of this
   * scan failed on `muiTheme.ts`'s docstring saying exactly that. Same trap as
   * the `jobFeed.` substring scan and `AppProviders.test.tsx`.)
   */
  const code = (src: string): string =>
    src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1')

  it('there are files to scan', () => {
    expect(files.length).toBeGreaterThan(10)
  })

  it('the pattern matches the thing it forbids', () => {
    expect(WEIGHT_800.test('fontWeight: 800')).toBe(true)
    expect(WEIGHT_800.test("fontWeight: '800'")).toBe(true)
    expect(WEIGHT_800.test('fontWeight: 600')).toBe(false)
  })

  it('and does not fire on prose that names it', () => {
    expect(WEIGHT_800.test(code('/* every fontWeight: 800 was swept */'))).toBe(false)
    expect(WEIGHT_800.test(code('// fontWeight: 800\nconst a = 1'))).toBe(false)
    // …while real code in the same file is still caught.
    expect(WEIGHT_800.test(code('// note\nconst x = { fontWeight: 800 }'))).toBe(true)
  })

  for (const [file, src] of files) {
    it(`${file} does not request 800`, () => {
      expect(code(src)).not.toMatch(WEIGHT_800)
    })
  }
})

describe('the slider is themed from tokens', () => {
  const theme = buildTheme('dark')
  const overrides = theme.components?.MuiSlider?.styleOverrides as Record<
    string,
    Record<string, unknown>
  >

  it('skins every slot a user can see', () => {
    for (const slot of ['root', 'rail', 'track', 'thumb', 'valueLabel', 'mark']) {
      expect(overrides[slot], `${slot} slot`).toBeTruthy()
    }
  })

  it('takes rail, track and thumb from palette tokens', () => {
    expect(overrides.rail.backgroundColor).toBe('var(--lgc-track)')
    expect(overrides.track.backgroundColor).toBe('var(--lgc-info)')
    expect(overrides.thumb.backgroundColor).toBe('var(--lgc-info)')
  })

  it('uses the same focus ring as the text fields', () => {
    // MuiOutlinedInput's focused ring is tint('info', 18); a slider that focuses
    // differently would look like a different design system.
    const hover = overrides.thumb['&:hover, &.Mui-focusVisible'] as { boxShadow: string }
    expect(hover.boxShadow).toContain('color-mix(in srgb')
    expect(hover.boxShadow).toContain('var(--lgc-info)')
    expect(hover.boxShadow).toContain('18%')
  })

  it('names no colour literal of its own', () => {
    const dump = JSON.stringify(overrides)
    expect(dump).not.toMatch(/#[0-9a-fA-F]{3,8}/)
    expect(dump).not.toMatch(/rgba?\(/)
  })
})
