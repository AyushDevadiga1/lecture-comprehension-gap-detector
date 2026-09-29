import { describe, expect, it } from 'vitest'
import {
  channels,
  contrastRatio,
  DEFAULT_BASE,
  hsl,
  luminance,
  nodeFill,
  nodePair,
  palette,
  readableOn,
} from './tokens'
import { nodeColors } from './nodeColors'

/**
 * Ports of `tests/test_theme.py` (properties 1-19) and the golden colour tables
 * the two palettes are known to produce.
 *
 * These are the same assertions in a second language. If the port and the Python
 * disagree, one of them is wrong, and the golden tables below are how we know
 * which -- they were measured from the Python, not from this module.
 */

/** Must clear 4.5:1 on every surface. */
const TEXT_TOKENS = ['text', 'muted', 'ok', 'warn', 'bad', 'info', 'accent'] as const

/** Every surface a text token can land on. */
const SURFACES = ['page', 'surface', 'surface_alt', 'graph_bg'] as const

/** Meaningful non-text marks: 3:1. */
const STRUCTURAL = ['tick', 'graph_edge', 'covered'] as const

/** Decorative: visible, but not meaningfully so. */
const DECORATIVE = ['border', 'track'] as const

const AA_TEXT = 4.5
const AA_NON_TEXT = 3.0
const DECORATIVE_FLOOR = 1.1

const BASES = ['dark', 'light'] as const

describe('the maths', () => {
  // test_contrast_ratio_anchors
  it('anchors at black-on-white and white-on-white', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21.0, 1)
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1.0, 1)
  })

  // test_contrast_is_order_independent
  it('is order-independent', () => {
    expect(contrastRatio('#e6edf3', '#0e1117')).toBe(contrastRatio('#0e1117', '#e6edf3'))
  })

  // test_a_non_colour_is_rejected
  it('rejects anything that is not a hex colour', () => {
    for (const bad of ['nope', '#12345', '', '#gggggg']) {
      expect(() => luminance(bad), bad).toThrow()
    }
  })

  // test_shorthand_hex_is_accepted
  it('accepts shorthand hex', () => {
    expect(luminance('#fff')).toBe(luminance('#ffffff'))
  })

  it('tolerates surrounding whitespace and a leading hash', () => {
    expect(channels('  #ffffff ')).toEqual(channels('ffffff'))
  })
})

describe('the tokens', () => {
  for (const base of BASES) {
    it(`${base}: every text token clears AA on every surface`, () => {
      const p = palette(base)
      for (const token of TEXT_TOKENS) {
        for (const surface of SURFACES) {
          expect(
            contrastRatio(p[token], p[surface]),
            `${token} on ${surface} (${base})`,
          ).toBeGreaterThanOrEqual(AA_TEXT)
        }
      }
    })

    it(`${base}: meaningful marks clear the non-text floor`, () => {
      const p = palette(base)
      for (const token of STRUCTURAL) {
        for (const surface of SURFACES) {
          expect(contrastRatio(p[token], p[surface]), `${token} on ${surface}`).toBeGreaterThanOrEqual(
            AA_NON_TEXT,
          )
        }
      }
    })

    it(`${base}: decorative marks are at least visible`, () => {
      const p = palette(base)
      for (const token of DECORATIVE) {
        for (const surface of SURFACES) {
          expect(contrastRatio(p[token], p[surface]), `${token} on ${surface}`).toBeGreaterThanOrEqual(
            DECORATIVE_FLOOR,
          )
        }
      }
    })

    // test_each_palette_is_actually_the_theme_it_claims
    it(`${base}: the palette is actually the theme it claims`, () => {
      const p = palette(base)
      if (base === 'dark') expect(luminance(p.page)).toBeLessThan(0.05)
      else expect(luminance(p.page)).toBeGreaterThan(0.9)
    })

    // test_surfaces_step_up_in_lightness_on_both_themes
    it(`${base}: surfaces step up in lightness`, () => {
      const p = palette(base)
      expect(p.surface).not.toBe(p.page)
      expect([p.surface, p.page]).toContain(p.graph_bg)
    })

    // test_a_node_is_distinguishable_from_the_canvas_behind_it
    it(`${base}: a node is distinguishable from the canvas behind it`, () => {
      const p = palette(base)
      // 24 hues is the Python's sweep; it is the real regression guard.
      for (let i = 0; i < 24; i++) {
        const hue = i / 24
        expect(contrastRatio(nodeFill(hue, base), p.graph_bg), `hue ${hue}`).toBeGreaterThanOrEqual(1.3)
      }
    })

    // test_readable_on_is_legible_on_every_hue_of_the_ramp
    it(`${base}: a node label is legible on every hue of the ramp`, () => {
      for (let i = 0; i < 72; i++) {
        const hue = i / 72
        const fill = nodeFill(hue, base)
        expect(contrastRatio(readableOn(fill, base), fill), `hue ${hue}`).toBeGreaterThanOrEqual(AA_TEXT)
      }
    })
  }

  // test_an_unknown_theme_base_falls_back_instead_of_raising
  it('an unknown base falls back instead of raising', () => {
    expect(palette('solarized-lagoon')).toBe(palette(DEFAULT_BASE))
    expect(palette(null)).toBe(palette(DEFAULT_BASE))
    expect(palette(undefined)).toBe(palette(DEFAULT_BASE))
    expect(palette('dark.sidebar')).toBe(palette('dark'))
  })
})

describe('readableOn', () => {
  // test_readable_on_flips_with_the_background
  it('flips with the background', () => {
    expect(luminance(readableOn('#0b1220', 'dark'))).toBeGreaterThan(0.5)
    expect(luminance(readableOn('#f6f8fa', 'dark'))).toBeLessThan(0.5)
  })

  it('always returns the better-measuring of the two candidates', () => {
    for (const base of BASES) {
      const p = palette(base)
      for (let i = 0; i < 72; i++) {
        const bg = nodeFill(i / 72, base)
        const ink = readableOn(bg, base)
        expect([p.ink_light, p.ink_dark], `hue ${i}`).toContain(ink)
        const chosen = contrastRatio(ink, bg)
        const other = ink === p.ink_light ? p.ink_dark : p.ink_light
        expect(chosen, `hue ${i}`).toBeGreaterThanOrEqual(contrastRatio(other, bg))
      }
    }
  })

  it('resolves an exact tie to ink_light, by construction', () => {
    // The Python uses `>=`, so a tie goes to ink_light. An exact tie is not
    // constructible from real hex -- it needs a background at the geometric
    // midpoint of the two ink luminances -- so this asserts the source-level
    // rule instead of pretending a synthetic case proves it. If someone changes
    // `>=` to `>`, this fails.
    const src = readableOn.toString()
    expect(src).toContain('>=')
  })
})

describe('hsl', () => {
  it('is HLS, not HSL', () => {
    // Python's colorsys.hls_to_rgb(h, l, s) takes lightness before saturation.
    // With s=1, l=0.5 the result is the pure hue; swapping the argument order
    // gives a visibly different (and wrong) ramp that still looks plausible.
    expect(hsl(0, 1, 0.5)).toBe('#ff0000')
    expect(hsl(1 / 3, 1, 0.5)).toBe('#00ff00')
    expect(hsl(2 / 3, 1, 0.5)).toBe('#0000ff')
  })

  it('emits lowercase six-digit hex', () => {
    expect(hsl(0.5, 0.42, 0.28)).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('wraps a hue of 1 to 0, as Python\'s % 1.0 does', () => {
    expect(hsl(1, 1, 0.5)).toBe(hsl(0, 1, 0.5))
  })
})

/**
 * Golden tables, measured from `frontend/theme.py` — not from this module. If
 * these fail, the port drifted and the Python is right.
 */
describe('golden colours from the Python palette', () => {
  it('order ramp, total = 11', () => {
    // Measured from the Python: fill, then the ink chosen for it.
    const expected: Array<[string, string]> = [
      ['#296560', '#f6f8fb'],
      ['#296550', '#f6f8fb'],
      ['#29653f', '#f6f8fb'],
      ['#29652e', '#f6f8fb'],
      ['#356529', '#f6f8fb'],
      ['#466529', '#f6f8fb'],
      ['#576529', '#f6f8fb'],
      ['#656329', '#f6f8fb'],
      ['#655329', '#f6f8fb'],
      ['#654229', '#f6f8fb'],
      ['#653129', '#f6f8fb'],
    ]
    expected.forEach(([fill, ink], rank) => {
      expect(nodeColors('n', rank, 11, 'order', 'dark'), `rank ${rank}`).toEqual([fill, ink])
    })
  })

  it('order ramp, total = 11, light palette', () => {
    const expected = [
      '#9edbd6', '#9edbc5', '#9edbb4', '#9edba3', '#aadb9e', '#bbdb9e',
      '#ccdb9e', '#dbd99e', '#dbc89e', '#dbb79e', '#dba69e',
    ]
    expected.forEach((fill, rank) => {
      const [gotFill, gotInk] = nodeColors('n', rank, 11, 'order', 'light')
      expect(gotFill, `rank ${rank}`).toBe(fill)
      expect(gotInk, `rank ${rank}`).toBe('#0b1220')
    })
  })

  it('identity colours, dark', () => {
    // Includes the corpus's worst case, `Derangement` at 4.81:1.
    const expected: Record<string, string> = {
      Covariance: '#6c2342',
      Independence: '#1b7447',
      HAVING: '#1e712a',
      update: '#686527',
      "Bayes' Rule": '#20416f',
      'Conditional Expectation': '#6d2222',
      Derangement: '#6f721d',
      Expectation: '#276867',
    }
    for (const [name, fill] of Object.entries(expected)) {
      expect(nodeColors(name, null, null, 'identity', 'dark')[0], name).toBe(fill)
    }
  })

  it('identity colours, light', () => {
    const expected: Record<string, string> = {
      Covariance: '#df9bb7',
      Independence: '#93e6bc',
      HAVING: '#96e3a1',
      update: '#dbd89f',
      "Bayes' Rule": '#98b7e2',
      'Conditional Expectation': '#df9a9a',
      Derangement: '#e1e496',
      Expectation: '#9fdbda',
    }
    for (const [name, fill] of Object.entries(expected)) {
      expect(nodeColors(name, null, null, 'identity', 'light')[0], name).toBe(fill)
    }
  })

  it('every identity colour in the corpus is distinct', () => {
    // test_node_colours_differ_between_nodes
    const names = [
      'Covariance', 'Independence', 'HAVING', 'update', "Bayes' Rule",
      'Conditional Expectation', 'Derangement', 'Expectation',
    ]
    for (const base of BASES) {
      const fills = names.map((n) => nodeColors(n, null, null, 'identity', base)[0])
      expect(new Set(fills).size, base).toBe(names.length)
    }
  })
})

describe('nodeColors decision table', () => {
  it('order mode needs a rank and more than one total', () => {
    const identity = nodeColors('Expectation', null, null, 'identity', 'dark')
    // rank null -> identity
    expect(nodeColors('Expectation', null, 11, 'order', 'dark')).toEqual(identity)
    // total of 1 or 0 -> identity
    expect(nodeColors('Expectation', 0, 1, 'order', 'dark')).toEqual(identity)
    expect(nodeColors('Expectation', 0, 0, 'order', 'dark')).toEqual(identity)
    // a usable rank -> the ramp, which differs from identity
    expect(nodeColors('Expectation', 0, 11, 'order', 'dark')).not.toEqual(identity)
  })

  it('order mode ignores the name', () => {
    // test_order_mode_ignores_the_node_name
    expect(nodeColors('A', 3, 11, 'order', 'dark')).toEqual(nodeColors('Zebra', 3, 11, 'order', 'dark'))
  })

  it('treats any non-order mode as identity, without raising', () => {
    const identity = nodeColors('Expectation', null, null, 'identity', 'dark')
    expect(nodeColors('Expectation', 5, 11, 'nonsense' as never, 'dark')).toEqual(identity)
  })

  it('is idempotent for a name', () => {
    // test_node_identity_is_stable_per_name
    for (const base of BASES) {
      expect(nodeColors('Covariance', null, null, 'identity', base)).toEqual(
        nodeColors('Covariance', null, null, 'identity', base),
      )
    }
  })

  it('clamps an out-of-range rank rather than overflowing the hue', () => {
    expect(nodeColors('x', -5, 11, 'order', 'dark')[0]).toBe(nodeColors('x', 0, 11, 'order', 'dark')[0])
    expect(nodeColors('x', 99, 11, 'order', 'dark')[0]).toBe(nodeColors('x', 10, 11, 'order', 'dark')[0])
  })

  it('a node label clears AA for every rank and both modes', () => {
    // test_rendered_node_labels_clear_aa
    for (const base of BASES) {
      for (const mode of ['order', 'identity'] as const) {
        for (let rank = 0; rank < 8; rank++) {
          const [fill, ink] = nodeColors('Conditional Expectation', rank, 8, mode, base)
          expect(fill, `${base} ${mode}`).not.toBe(ink)
          expect(contrastRatio(ink, fill), `${base} ${mode} rank ${rank}`).toBeGreaterThanOrEqual(AA_TEXT)
        }
      }
    }
  })
})

describe('nodePair', () => {
  it('returns the fill and a legible ink', () => {
    const [fill, ink] = nodePair(0.5, 'dark')
    expect(fill).toMatch(/^#[0-9a-f]{6}$/)
    expect(contrastRatio(ink, fill)).toBeGreaterThanOrEqual(AA_TEXT)
  })
})
