/**
 * The colour system, ported from `frontend/theme.py`.
 *
 * REACT_ARCHITECTURE.md §4: "`frontend/theme.py` is the single source of colour
 * truth... If the React app picks its own colours, the app has two palettes and
 * one of them is untested." At the time of writing it *did* — this module is the
 * other one, so the two can no longer disagree without a test failing
 * (`src/theme/theme.test.ts` and `tests/test_contract.py`'s sibling,
 * `scripts/check_theme_parity.py`).
 *
 * Ported literally, not redesigned. The Python is pinned by 26 property tests in
 * `tests/test_theme.py`, and the behaviour those tests assert is the contract:
 *
 *   - `luminance` / `contrast_ratio` are WCAG 2.1, order-independent.
 *   - `readableOn` picks whichever of two ink candidates *measures* better, so
 *     a label is legible whatever it lands on. The `>=` means a tie goes to
 *     `ink_light`, and that is preserved.
 *   - `nodeFill` always uses the palette's lightness; only saturation is
 *     overridable, which is why identity mode varies hue and saturation but
 *     never lightness.
 *   - `hsl` is HLS, not HSL. Python's `colorsys.hls_to_rgb(h, l, s)` takes
 *     lightness *before* saturation; getting the order wrong produces a
 *     completely different ramp that still looks plausible.
 *   - `Math.round` is safe where Python uses banker's rounding: across the whole
 *     3600-step hue sweep no channel lands on an exact `.5` for either
 *     palette's `node_light`/`node_sat`, so the two agree byte for byte. The
 *     golden tables in the test suite are the proof.
 */

export type Base = 'dark' | 'light'

export const DARK: Base = 'dark'
export const LIGHT: Base = 'light'
export const DEFAULT_BASE: Base = DARK

/** WCAG 2.1 relative-luminance sRGB coefficients. */
const C = [0.2126, 0.7152, 0.0722] as const

export interface Palette {
  base: Base
  /** Page background. Must equal the CSS body background. */
  page: string
  /** Cards, scroll boxes, the DAG canvas. */
  surface: string
  /** Table header stripe, hover bands. The *darkest* surface a token may land on. */
  surface_alt: string
  border: string
  text: string
  muted: string
  ok: string
  warn: string
  bad: string
  info: string
  accent: string
  graph_bg: string
  graph_edge: string
  /** The "not covered" part of the timeline. */
  track: string
  /** Transcript ticks. */
  tick: string
  /** Concept-covered spans on the timeline. */
  covered: string
  /** The two ink candidates a node, badge or chip may get. */
  ink_light: string
  ink_dark: string
  /**
   * HSL lightness for every node fill. Not arbitrary: the lightest value that
   * still keeps the block visible against the canvas (1.32:1) while every hue
   * clears 5.7:1 against its own label. Darker hides the node; lighter costs
   * label legibility.
   */
  node_light: number
  node_sat: number
}

/**
 * Dark is the base the app ships with, and the one the Streamlit engine declares
 * in `.streamlit/config.toml`. Surfaces step up in lightness so a card reads as
 * a card; text steps down from near-white. Every value is contrast-checked in
 * `tests/test_theme.py` rather than eyeballed.
 */
const DARK_PALETTE: Palette = {
  base: DARK,
  page: '#0e1117',
  surface: '#161b22',
  surface_alt: '#1c2330',
  border: '#30363d',
  text: '#e6edf3',
  muted: '#9aa7b4',
  ok: '#57d364',
  warn: '#e3b341',
  bad: '#f85149',
  info: '#58a6ff',
  accent: '#58a6ff',
  graph_bg: '#161b22',
  graph_edge: '#6e7681',
  track: '#2f3742',
  tick: '#6e7681',
  covered: '#2ea043',
  ink_light: '#f6f8fb',
  ink_dark: '#0a0e14',
  node_light: 0.28,
  node_sat: 0.42,
}

/**
 * Light is present so the app is not silently broken if someone flips the theme.
 * The status hues are a step darker than their usual web values *precisely*
 * because they must clear 4.5:1 on the darkest surface they can land on
 * (`surface_alt`), not just on white — the familiar #1a7f37 / #9a6700 / #0969da
 * sit at 4.2–4.5:1 there and fail.
 */
const LIGHT_PALETTE: Palette = {
  base: LIGHT,
  page: '#ffffff',
  surface: '#f6f8fa',
  surface_alt: '#eaeef2',
  border: '#d0d7de',
  text: '#1f2328',
  muted: '#59636e',
  ok: '#16642c',
  warn: '#8a5b00',
  bad: '#cf222e',
  info: '#0b5cad',
  accent: '#0b5cad',
  graph_bg: '#f6f8fa',
  graph_edge: '#656e76',
  track: '#d0d6de',
  tick: '#767f8a',
  covered: '#1a7f37',
  ink_light: '#ffffff',
  ink_dark: '#0b1220',
  node_light: 0.74,
  node_sat: 0.46,
}

const PALETTES: Record<Base, Palette> = {
  [DARK]: DARK_PALETTE,
  [LIGHT]: LIGHT_PALETTE,
}

// ---------------------------------------------------------------------- maths

/**
 * `(r, g, b)` in 0..1 from `#rgb` or `#rrggbb`.
 *
 * Throws on anything else, deliberately: `tests/test_theme.py::
 * test_a_non_colour_is_rejected` pins that a bad colour fails loudly rather than
 * silently becoming black, because a silently-black fill is a legibility bug
 * that looks fine in a screenshot.
 */
export function channels(hexColour: string): [number, number, number] {
  let text = String(hexColour).trim().replace(/^#/, '')
  if (text.length === 3) text = text.split('').map((ch) => ch + ch).join('')
  if (text.length !== 6) throw new Error(`not a hex colour: ${hexColour}`)
  const pair = (i: number) => parseInt(text.slice(i, i + 2), 16) / 255
  if ([0, 2, 4].some((i) => Number.isNaN(pair(i)))) {
    throw new Error(`not a hex colour: ${hexColour}`)
  }
  return [pair(0), pair(2), pair(4)]
}

const linearise = (c: number): number => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)

/** WCAG relative luminance: 0 = black, 1 = white. */
export function luminance(hexColour: string): number {
  const [r, g, b] = channels(hexColour)
  return C[0] * linearise(r) + C[1] * linearise(g) + C[2] * linearise(b)
}

/** WCAG contrast ratio, 1:1 .. 21:1. Order-independent. */
export function contrastRatio(foreground: string, background: string): number {
  const a = luminance(foreground)
  const b = luminance(background)
  const hi = Math.max(a, b)
  const lo = Math.min(a, b)
  return (hi + 0.05) / (lo + 0.05)
}

/**
 * Python's `colorsys.hls_to_rgb`, bit for bit. Note the argument order: **H, L,
 * S** — not H, S, L. The Python signature is `hls_to_rgb(h, l, s)`.
 */
function hlsToRgb(h: number, l: number, s: number): [number, number, number] {
  const m2 = l <= 0.5 ? l * (s + 1) : l + s - l * s
  const m1 = l * 2 - m2
  const v = (hue: number): number => {
    let x = hue % 1
    if (x < 0) x += 1
    if (x < 1 / 6) return m1 + (m2 - m1) * x * 6
    if (x < 1 / 2) return m2
    if (x < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - x) * 6
    return m1
  }
  return [v(h + 1 / 3), v(h), v(h - 1 / 3)]
}

/** `#rrggbb`, lowercase. `h` is in turns, like Python's 0..1 hue. */
export function hsl(h: number, s: number, light: number): string {
  // Python's `% 1.0` already returns a non-negative result for a negative
  // operand, so this mirrors that rather than JS's negative `%`.
  const hue = ((h % 1) + 1) % 1
  const rgb = hlsToRgb(hue, light, s)
  return (
    '#' +
    rgb
      .map((c) => Math.round(c * 255).toString(16).padStart(2, '0'))
      .join('')
  )
}

// ------------------------------------------------------------------- palettes

/**
 * Tokens for a theme base. Unknown or missing bases fall back to the shipped
 * default — never throws, because a renderer must not fail because a theme is
 * unknown. `"dark.sidebar"` normalises to `"dark"`, which is why the split on
 * `.` is here at all.
 */
export function palette(base?: string | null): Palette {
  if (base == null) return PALETTES[DEFAULT_BASE]
  const key = String(base).toLowerCase().split('.')[0] as Base
  return PALETTES[key] ?? PALETTES[DEFAULT_BASE]
}

/**
 * The ink to put *on* `background` — the point of this whole module.
 *
 * Picks whichever of the palette's two ink candidates measures better, so a node
 * label, a badge or a filled chip is legible whatever colour it landed on. The
 * `>=` means a tie goes to `ink_light`, matching the Python.
 */
export function readableOn(background: string, base?: string | null): string {
  const pal = palette(base ?? undefined)
  const { ink_light: light, ink_dark: dark } = pal
  return contrastRatio(light, background) >= contrastRatio(dark, background) ? light : dark
}

/**
 * A node fill for a hue. Lightness is always the palette's; only saturation is
 * overridable — so identity mode varies hue and saturation but never lightness,
 * and every node stays the same visual weight.
 */
export function nodeFill(hue: number, base?: string | null, sat?: number): string {
  const pal = palette(base ?? undefined)
  return hsl(hue, sat ?? pal.node_sat, pal.node_light)
}

/** A node fill plus the ink that is legible on it. */
export function nodePair(hue: number, base?: string | null, sat?: number): [string, string] {
  const fill = nodeFill(hue, base ?? undefined, sat)
  return [fill, readableOn(fill, base ?? undefined)]
}
