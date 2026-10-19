import type { ConceptOut, SegmentOut } from '../api/types'
import { nodeFill, readableOn } from '../theme/tokens'

/**
 * The lecture coverage timeline — pure model.
 *
 * Ported from `frontend/render.py::lecture_html`, `_merge` and
 * `_support_sentence` on `main`. Python rendered a self-contained static
 * HTML/SVG island; this ports the same drawing to React, but the *numbers*
 * are the contract, not the syntax: every golden in `coverageTimeline.test.ts`
 * below was measured by running the real `render.py` on a fixture lecture and
 * parsing its output — merged runs, the coverage percentage, band geometry
 * and titles, support sentences, the caption string, rounding probes — never
 * by deriving values by hand (that mistake was made once on `graphImportance`
 * and the Python caught it).
 *
 * Detail the port preserves because the tests pin it:
 *
 * - `_merge` merges when `start <= last end` — touching windows merge into
 *   one run, so the timeline draws one rect per run and a lecture's true
 *   gaps stay visible gaps.
 * - Coverage is `merged union / duration`, never a sum of concept lengths.
 *   Two overlapping concepts must not count the overlap twice.
 * - A concept with an unparsable window (`end_s: "oops"`) draws no span and
 *   no band, but still counts in the caption and still appears as a row —
 *   and its *start* still stretches the axis: the Python's duration loop
 *   ignores a failing term but not its sibling key.
 * - A concept with a falsy `end_s` (0, "", missing) is a zero-length window
 *   pinned at `start`, not an open join and not an error.
 * - Band order is taught order (the concepts array), never time order —
 *   unsorted input does not shuffle bands.
 * - Python's `%.*f` is round-half-to-even on the true binary value; JS
 *   `toFixed` rounds an exact tie away from zero. Everything the renderer
 *   prints goes through `pyFixed`, not raw `toFixed`.
 * - `[:160]` clips at 160 code *points*; a UTF-16 `slice(0, 160)` keeps 80
 *   astral glyphs and misrenders at the boundary.
 *
 * Band fill/ink come from `nodeFill`/`readableOn` in `src/theme/tokens` —
 * the same token path the DAG uses — so a concept colours identically in the
 * timeline and in the map (the theme golden tables in `theme.test.ts` pin
 * that module against the Python; this port does not re-pin these hexes).
 */

/** A half-open time window, in lecture seconds. */
export interface TimelineSpan {
  start: number
  end: number
}

/** One green rect on the track: one merged run, never one per concept. */
export interface TimelineRun {
  x: number
  width: number
  /** `covered: 10.0s–45.0s` — byte-identical to the Python's `<title>`. */
  title: string
}

/** One concept band in taught order plus its label bookkeeping. */
export interface TimelineBand {
  name: string
  a: number
  b: number
  x: number
  top: number
  width: number
  fill: string
  ink: string
  labelX: number
  labelY: number
  /** `name — 10.0s–25.0s` — byte-identical to the Python's `<title>`. */
  title: string
}

export interface TimelineRow {
  /** 1-based, over ALL concepts, including unparsable ones. */
  index: number
  name: string
  /** `48.0 – 51.0s`, or `—` when the window never parsed. */
  window: string
  /** The quiz-grade grounding sentence, or `—` when nothing mentions it. */
  support: string
}

/**
 * Everything the component renders, with no react in it. Payload in, model
 * out — the unit tests run this with no DOM at all, exactly as `lecture_html`
 * was tested.
 */
export interface TimelineModel {
  title: string
  width: number
  /** `height`/viewBox height: 78 + 27 per *drawn* band. */
  svgHeight: number
  duration: number
  coveredSeconds: number
  /** `coveredSeconds / duration` — the union, NOT a sum of concept windows. */
  coverage: number
  /** The Python `%.*f` strings behind the caption — the component renders
   * these, so the formatting decisions live in exactly one place. */
  pctText: string
  coveredText: string
  durationText: string
  /** Raw concept count, including concept rows the drawing skips. */
  nConcepts: number
  nSegments: number
  /**
   * The whole caption line: `9 concepts · 5 transcript segments · 61% of the
   * lecture covered by extracted concepts (38s of 62s).` — measured bytes.
   */
  captionPlain: string
  /** What the caption bolds: `61% of the lecture covered`. */
  captionBold: string
  /** Merged runs, for tests that want the naked numbers. */
  merged: TimelineSpan[]
  ticks: Array<{ x: number }>
  coveredRects: TimelineRun[]
  bands: TimelineBand[]
  axisStart: { x: number; text: string }
  /** Right-hand duration label — may exceed max segment end (see docstring). */
  axisEnd: { x: number; text: string }
  rows: TimelineRow[]
}

/**
 * Python `float()`: numbers straight through (NaN included, like Python's
 * `float(nan)`), booleans to 1/0, numeric strings via `Number`. Anything
 * else — nullish, objects, arrays — throws, like `float(None)` does. The one
 * accepted divergence: a hex string parses where Python's float raises, which
 * no payload in this system ever contains.
 */
export function pyNumber(value: unknown): number {
  if (typeof value === 'number') return value
  if (typeof value === 'boolean') return value ? 1 : 0
  if (typeof value === 'string') {
    const n = Number(value)
    if (Number.isNaN(n)) throw new TypeError(`float(): cannot parse ${JSON.stringify(value)}`)
    return n
  }
  throw new TypeError(`float(): argument must be a number or a numeric string, got ${typeof value}`)
}

/** `value or fallback` in float context. Python falsy: None, 0, '', False. */
function pyOr(value: unknown, fallback: number): number {
  return value == null || value === false || value === 0 || value === ''
    ? fallback
    : pyNumber(value)
}

/**
 * Python's `%.*f` — round-half-to-even on the true binary value.
 *
 * `toFixed` is close but not equal: it rounds an *exact*“.5” tail away from
 * zero (`(2.5).toFixed(0)` is `3`, Python prints `2`), and it can round the
 * binary tail that decides a tie the wrong way when it cuts to too few
 * digits. This format works on a 20-digit-guarded decimal expansion instead,
 * so a tail like `0.05000000000000000277…` is correctly read as *above* the
 * tie, and a true tie goes to the even digit. Goldens measured from Python
 * in `coverageTimeline.test.ts` pin all the interesting cases.
 */
export function pyFixed(value: number, decimals: number): string {
  if (!Number.isFinite(value)) throw new RangeError(`not a finite number: ${String(value)}`)
  if (!Number.isInteger(decimals) || decimals < 0 || decimals > 20) {
    throw new RangeError(`bad decimals: ${decimals}`)
  }
  const probe = value.toFixed(decimals + 20)
  const negative = probe.startsWith('-')
  const magnitude = negative ? probe.slice(1) : probe
  const dot = magnitude.indexOf('.')
  let intPart = magnitude.slice(0, dot)
  const frac = magnitude.slice(dot + 1)
  let outFrac = frac.slice(0, decimals)
  const discard = frac.slice(decimals)

  if (discard.length > 0) {
    const first = discard.charCodeAt(0) ?? 0
    const restZero = /^0*$/.test(discard.slice(1))
    // Half-even: a 5 followed by nothing but zeros is an exact tie and goes
    // to the even last digit; anything above rounds up, below rounds down.
    const lastDigit =
      decimals > 0
        ? outFrac[outFrac.length - 1] ?? intPart[intPart.length - 1] ?? '0'
        : intPart[intPart.length - 1] ?? '0'
    const bump =
      first > 53 /* '5' */ ||
      (first === 53 && !restZero) ||
      (first === 53 && restZero && Number(lastDigit) % 2 === 1)
    if (bump) {
      const combined = [...(intPart + outFrac)]
      let i = combined.length - 1
      while (i >= 0 && combined[i] === '9') {
        combined[i] = '0'
        i--
      }
      if (i < 0) {
        intPart = `1${combined.join('')}` // all nines: 999.99 -> 1000.00
        outFrac = '0'.repeat(decimals)
      } else {
        combined[i] = String(Number(combined[i]) + 1)
        intPart = combined.slice(0, intPart.length).join('')
        outFrac = combined.slice(intPart.length).join('')
      }
    }
  }
  return `${negative ? '-' : ''}${intPart}${decimals > 0 ? `.${outFrac}` : ''}`
}

/** Python string length: code points, not UTF-16 units (`.length` overcounts). */
function codePointLength(text: string): number {
  return [...text].length
}

/** Collapse whitespace runs to single spaces and trim — Python's `" ".join(s.split())`. */
function collapse(text: string): string {
  return String(text).split(/\s+/).join(' ').trim()
}

/**
 * `_merge`: merge overlapping time spans into sorted covered ranges.
 * Adjacent (touching) windows merge too — `start <= last end` — which is the
 * one-rect-per-run property that keeps real gaps visible on the track.
 */
export function mergeSpans(spans: readonly TimelineSpan[]): TimelineSpan[] {
  const sorted = [...spans].sort((a, b) => a.start - b.start || a.end - b.end)
  const merged: TimelineSpan[] = []
  for (const span of sorted) {
    const last = merged[merged.length - 1]
    if (last && span.start <= last.end) last.end = Math.max(last.end, span.end)
    else merged.push({ start: span.start, end: span.end })
  }
  return merged
}

export const SUPPORT_CLIP = 160

/**
 * `_support_sentence`: the shortest transcript segment mentioning `concept`.
 * Case-insensitive substring; whitespace in the segment is collapsed before
 * comparing (so a spoken line with irregular spacing still grounds the
 * concept); the answer clips at ${SUPPORT_CLIP.toString()} code points.
 * No match returns "".
 */
export function supportSentence(
  concept: string,
  segments: readonly SegmentOut[] | null | undefined,
): string {
  const needle = concept.toLowerCase()
  let best: string | null = null
  for (const segment of segments ?? []) {
    const text = collapse(String(segment.text ?? ''))
    if (!text.toLowerCase().includes(needle)) continue
    if (best === null || codePointLength(text) < codePointLength(best)) best = text
  }
  if (best === null) return ''
  // Clamp in code points, like Python's [:160] — slicing UTF-16 units would
  // keep stragglers (an emoji-inclusive sentence keeps only half as many).
  return Array.from(best)
    .slice(0, SUPPORT_CLIP)
    .join('')
}

/**
 * Build the whole timeline model. Mirrors `lecture_html` step for step:
 *
 *   1. duration = 1s floor, then the max end anywhere (segment ends strictly,
 *      concept ends defensively — see the header);
 *   2. x(t) = t / duration * width;
 *   3. transcript ticks for every segment start;
 *   4. spans parsed (unparsable windows skipped), merged into runs, coverage
 *      = merged union / duration;
 *   5. one band per *drawn* concept, in taught order, teal→coral ramp;
 *   6. one row per concept, in array order, whatever it drew.
 */
export function buildTimelineModel(
  segments: readonly SegmentOut[] | null | undefined,
  concepts: readonly ConceptOut[] | null | undefined,
  lectureTitle: string = '',
  width: number = 1000,
): TimelineModel {
  const segmentList = segments ?? []
  const conceptList = concepts ?? []
  const conceptFields = (concept: ConceptOut): Record<string, unknown> =>
    concept as unknown as Record<string, unknown>

  let duration = 1.0
  for (const segment of segmentList) {
    // No try on segment ends, exactly like the Python: a bad one is a loud
    // type violation, not silently clipped time.
    duration = Math.max(duration, pyNumber(segment.end_s))
  }
  for (const concept of conceptList) {
    for (const key of ['end_s', 'start_s'] as const) {
      const raw = conceptFields(concept)[key]
      try {
        duration = Math.max(duration, pyOr(raw, 0))
      } catch {
        // float() raised; the Python's duration loop skips the term.
      }
    }
  }

  const xOf = (t: number): number => (t / duration) * width

  /**
   * The window parse the Python repeats three times: `a = float(start or 0)`,
   * `b = float(end or a)`. A falsy end pins `b` at `a` — a zero-length
   * window. Note `b` may still be below `a` with an inverted window; the
   * Python clamps via max(a,0)/max(b,a) at push time and renders what falls
   * out (a sliver), rather than special-casing it.
   */
  const parseWindow = (concept: ConceptOut): { start: number; end: number } => {
    const rawStart = conceptFields(concept).start_s
    const rawEnd = conceptFields(concept).end_s
    const start = pyOr(rawStart, 0)
    const end =
      rawEnd == null || rawEnd === false || rawEnd === 0 || rawEnd === ''
        ? start
        : pyNumber(rawEnd)
    return { start, end }
  }

  const ticks = segmentList.map((segment) => ({ x: xOf(segment.start_s) }))

  const spans: TimelineSpan[] = []
  for (const concept of conceptList) {
    try {
      const { start, end } = parseWindow(concept)
      spans.push({ start: Math.max(start, 0), end: Math.max(end, start) })
    } catch {
      continue
    }
  }

  const merged = mergeSpans(spans)
  const coveredSeconds = merged.reduce((acc, run) => acc + (run.end - run.start), 0)
  const coverage = coveredSeconds / duration

  const coveredRects: TimelineRun[] = merged.map(({ start, end }) => ({
    x: xOf(start),
    // one px floor: a zero-length run still shows as a sliver rather than
    // invisibly "rounding away"
    width: Math.max(xOf(end) - xOf(start), 1),
    title: `covered: ${pyFixed(start, 1)}s–${pyFixed(end, 1)}s`,
  }))

  const bands: TimelineBand[] = []
  let taught = 0
  for (const concept of conceptList) {
    const name = concept.name ?? '?'
    try {
      const { start, end } = parseWindow(concept)
      // teal → coral along the taught index, the DAG's order ramp; the
      // denominator counts ALL concepts, so a skipped one leaves the ramp
      // short of its coral end. Same ramp constants as `nodeColors.ts`.
      const fraction = taught / Math.max(conceptList.length - 1, 1)
      const fill = nodeFill((175 + (8 - 175) * fraction) / 360)
      const ink = readableOn(fill)
      const top = 58 + 26 * taught
      bands.push({
        name,
        a: start,
        b: end,
        x: xOf(start),
        top,
        width: Math.max(xOf(end) - xOf(start), 2),
        fill,
        ink,
        // Python truncates toward zero here (int(x)), so a band label sits
        // at floor(x) + 6, not round(x) + 6.
        labelX: Math.trunc(xOf(start)) + 6,
        labelY: top + 15,
        title: `${name} — ${pyFixed(start, 1)}s–${pyFixed(end, 1)}s`,
      })
      taught += 1
    } catch {
      // unparsable window: no band, and the taught index does not advance
      // (the Python `continue`s) — but the row below still lists it.
    }
  }

  const rows: TimelineRow[] = []
  conceptList.forEach((concept, i) => {
    const name = concept.name ?? '?'
    let window: string
    try {
      const { start, end } = parseWindow(concept)
      window = `${pyFixed(start, 1)} – ${pyFixed(end, 1)}s`
    } catch {
      window = '—'
    }
    const support = supportSentence(name, segmentList)
    rows.push({
      index: i + 1,
      name,
      window,
      support: support === '' ? '—' : support,
    })
  })

  const pctText = pyFixed(coverage * 100, 0)
  const coveredText = pyFixed(coveredSeconds, 0)
  const durationText = pyFixed(duration, 0)
  const nConcepts = conceptList.length
  const nSegments = segmentList.length

  return {
    title: lectureTitle,
    width,
    svgHeight: 78 + 27 * taught,
    duration,
    coveredSeconds,
    coverage,
    nConcepts,
    nSegments,
    pctText,
    coveredText,
    durationText,
    captionPlain:
      `${nConcepts} concepts · ${nSegments} transcript segments · ` +
      `${pctText}% of the lecture covered by extracted concepts ` +
      `(${coveredText}s of ${durationText}s).`,
    captionBold: `${pctText}% of the lecture covered`,
    merged,
    ticks,
    coveredRects,
    bands,
    axisStart: { x: 0, text: '0s' },
    axisEnd: { x: width - 40, text: `${durationText}s` },
    rows,
  }
}
