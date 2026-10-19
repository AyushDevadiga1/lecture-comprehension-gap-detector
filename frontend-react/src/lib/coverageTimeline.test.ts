import { describe, expect, it } from 'vitest'
import type { ConceptOut, SegmentOut } from '../api/types'
import { nodeFill, readableOn } from '../theme/tokens'
import {
  buildTimelineModel,
  mergeSpans,
  pyFixed,
  supportSentence,
} from './coverageTimeline'

/**
 * Golden tests for the `lecture_html` port — the CoverageTimeline model.
 *
 * The fixture below ran through the REAL Python (`frontend/render.py::
 * lecture_html`, `_merge`, `_support_sentence`, all on `main`) and its output
 * was parsed back rather than recomputed. Every number and string asserted
 * here is what the Python printed, not what a human derived — the same
 * discipline `graphImportance.test.ts` was ported under (there the hand-
 * derived values were wrong and the Python caught it).
 *
 * Each fidelity trap gets its own fixture row and its own test:
 *   - overlapping windows AND adjacent (touching) windows, both merging;
 *   - zero-length spans, adjacent to a run (vanish into it) and standalone
 *     (their own run, still drawn, zero contribution);
 *   - the coverage percentage = merged union / duration, NOT a sum;
 *   - deterministic band order (taught order, not time order);
 *   - escaping of labels (`Br<&>k "x"`);
 *   - the 160-code-point support clip (an astral-fixture pin, where a
 *     UTF-16 slice would keep 80 glyphs instead of 160);
 *   - `%.*f` round-half-to-even, where `toFixed` rounds ties away.
 */

const FIXTURE_TITLE = 'Coverage — "Golden" <Fixture> · x&y'

// Kept verbatim from the measured fixture (JSON in the measurement run).
const FIXTURE_SEGMENTS: SegmentOut[] = [
  { idx: 0, start_s: 0, end_s: 8, text: 'Welcome. Today we trace the path from moments to variance.' },
  {
    idx: 1,
    start_s: 8,
    end_s: 20,
    text: 'The  expectation value  of position is the first moment of the wavefunction.\ttwo runs collapse here',
  },
  { idx: 2, start_s: 20, end_s: 28, text: 'expectation value' },
  {
    idx: 3,
    start_s: 28,
    end_s: 40,
    text: 'Note   the spacing:   whitespace runs collapse in the support sentence.',
  },
  {
    idx: 4,
    start_s: 40,
    end_s: 60,
    text: '  Kurtosis    measures the shape of the distribution tails: the fourth moment minus three, so a normal curve scores zero, and a heavy-tailed distribution scores large positive values, which is exactly what breaks the normal-approximation shortcut   ',
  },
]

const FIXTURE_CONCEPTS: ConceptOut[] = [
  // Band order deliberately disagrees with time order: this first concept
  // starts after the second one, so taught order is visible on its own.
  { id: 1, name: 'Wavefunction', source: 'x', implicit: false, start_s: 10, end_s: 25 },
  { id: 2, name: 'EXPECTATION VALUE', source: 'x', implicit: false, start_s: 18, end_s: 32 },
  { id: 3, name: 'the spacing', source: 'x', implicit: false, start_s: 32, end_s: 40 },
  { id: 4, name: 'Gaps', source: 'x', implicit: false, start_s: 40, end_s: 45 },
  { id: 5, name: 'Kurtosis', source: 'x', implicit: false, start_s: 48, end_s: 51 },
  // Zero-length span adjacent to (48, 51): merges INTO that run.
  { id: 6, name: 'Touching tail', source: 'x', implicit: false, start_s: 51, end_s: 51 },
  // Standalone zero-length span: own run, 0s of coverage, still drawn.
  { id: 7, name: 'Isolated zero', source: 'x', implicit: false, start_s: 56, end_s: 56 },
  // Unparsable window: no span, no band — but its start_s STILL stretches the
  // axis to 62s (the Python's duration loop keeps the sibling of a bad term),
  // and it still appears as a table row.
  {
    id: 8,
    name: 'Br<&>k "x"',
    source: 'x',
    implicit: false,
    start_s: 62,
    end_s: 'oops' as unknown as number,
  },
  // Falsy/missing end_s: zero-length window pinned at the start, not a gap
  // and not an error. Its (0,0) span becomes the first merged run.
  { id: 9, name: 'No window', source: 'x', implicit: false },
]

// Measured: lecture_html's rendered geometry (python % .1f strings), parsed
// back from the HTML the real function emitted.
const MEASURED_TICK_X = ['0.0', '129.0', '322.6', '451.6', '645.2'] as const
const MEASURED_RUN_TITLES = [
  'covered: 0.0s\u20130.0s',
  'covered: 10.0s\u201345.0s',
  'covered: 48.0s\u201351.0s',
  'covered: 56.0s\u201356.0s',
] as const
const MEASURED_RUN_GEOMETRY = [
  { x: '0.0', width: '1.0' },
  { x: '161.3', width: '564.5' },
  { x: '774.2', width: '48.4' },
  { x: '903.2', width: '1.0' },
] as const
const MEASURED_BAND_TOPS = [58, 84, 110, 136, 162, 188, 214, 240] as const
const MEASURED_BAND_LABEL_X = [167, 296, 522, 651, 780, 828, 909, 6] as const
const MEASURED_BAND_X = ['161.3', '290.3', '516.1', '645.2', '774.2', '822.6', '903.2', '0.0']
const MEASURED_BAND_WIDTHS = ['241.9', '225.8', '129.0', '80.6', '48.4', '2.0', '2.0', '2.0']
const MEASURED_BAND_TITLES = [
  'Wavefunction \u2014 10.0s\u201325.0s',
  'EXPECTATION VALUE \u2014 18.0s\u201332.0s',
  'the spacing \u2014 32.0s\u201340.0s',
  'Gaps \u2014 40.0s\u201345.0s',
  'Kurtosis \u2014 48.0s\u201351.0s',
  'Touching tail \u2014 51.0s\u201351.0s',
  'Isolated zero \u2014 56.0s\u201356.0s',
  'No window \u2014 0.0s\u20130.0s',
] as const

const model = buildTimelineModel(FIXTURE_SEGMENTS, FIXTURE_CONCEPTS, FIXTURE_TITLE)

describe('pyFixed — the Python %.*f printer', () => {
  it.each([
    // every [input, decimals, output] measured from Python `"%.*f" % v`
    [2.5, 0, '2'],
    [3.5, 0, '4'],
    [0.5, 0, '0'],
    [1.5, 0, '2'],
    [-0.5, 0, '-0'],
    [-2.5, 0, '-2'],
    [0.05, 1, '0.1'],
    [0.25, 1, '0.2'],
    [0.75, 1, '0.8'],
    [100.25, 1, '100.2'],
    [937.5, 1, '937.5'],
    [59.375, 0, '59'],
    [38.0, 0, '38'],
    [62.0, 0, '62'],
    // the coverage float itself: 0.6129… %.0f prints "1" — the caption only
    // says 61 because the Python multiplies by 100 BEFORE formatting.
    [38 / 62, 0, '1'],
  ])('%s at %i decimals prints %s', (value, decimals, expected) => {
    expect(pyFixed(value, decimals)).toBe(expected)
  })

  it('is not toFixed: an exact tie rounds half-to-even', () => {
    // (2.5).toFixed(0) is "3"; Python prints "2".
    expect((2.5).toFixed(0)).toBe('3')
    expect(pyFixed(2.5, 0)).toBe('2')
  })
})

describe('mergeSpans — golden fixture runs', () => {
  it('produces exactly the runs the Python drew (4 rects on the track)', () => {
    const spans = [
      { start: 10, end: 25 },
      { start: 18, end: 32 },
      { start: 32, end: 40 },
      { start: 40, end: 45 },
      { start: 48, end: 51 },
      { start: 51, end: 51 },
      { start: 56, end: 56 },
      { start: 0, end: 0 },
    ]
    expect(mergeSpans(spans)).toEqual(model.merged)
    expect(model.merged).toEqual([
      { start: 0, end: 0 },
      { start: 10, end: 45 },
      { start: 48, end: 51 },
      { start: 56, end: 56 },
    ])
  })

  it.each([
    // measured: render._merge(...) on the probe input, named for the trap
    ['adjacent', [[5, 10], [10, 12]], [[5, 12]]],
    ['contained', [[5, 10], [6, 8]], [[5, 10]]],
    ['between', [[0, 10], [5, 5], [12, 20]], [[0, 10], [12, 20]]],
    ['unsorted', [[10, 15], [5, 10], [30, 40]], [[5, 15], [30, 40]]],
    ['disjoint', [[5, 10], [2, 3]], [[2, 3], [5, 10]]],
  ])('%s windows give %j', (_name, spans, expected) => {
    expect(
      mergeSpans((spans as number[][]).map(([start, end]) => ({ start, end }))),
    ).toEqual((expected as number[][]).map(([start, end]) => ({ start, end })))
  })
})

describe('supportSentence — measured from _support_sentence', () => {
  it('picks the SHORTEST mentioning segment, not the first', () => {
    // 'EXPECTATION VALUE' matches segment 1 (long) and segment 2 (short).
    expect(supportSentence('EXPECTATION VALUE', FIXTURE_SEGMENTS)).toBe('expectation value')
  })

  it('matches case-insensitively and collapses whitespace runs', () => {
    expect(supportSentence('the spacing', FIXTURE_SEGMENTS)).toBe(
      'Note the spacing: whitespace runs collapse in the support sentence.',
    )
  })

  it('grounds a concept whose only mention sits in a messy segment', () => {
    expect(supportSentence('Wavefunction', FIXTURE_SEGMENTS)).toBe(
      'The expectation value of position is the first moment of the wavefunction. two runs collapse here',
    )
  })

  it('clips at exactly 160 code points, measured (the fixture is ASCII)', () => {
    const clipped = supportSentence('Kurtosis', FIXTURE_SEGMENTS)
    expect(clipped).toBe(
      'Kurtosis measures the shape of the distribution tails: the fourth moment minus three, so a normal curve scores zero, and a heavy-tailed distribution scores larg',
    )
    expect(clipped).toHaveLength(160)
  })

  it('clips astral text at 160 code POINTS, not UTF-16 units', () => {
    const astral = '\u{1F4A1}'.repeat(200)
    const got = supportSentence('\u{1F4A1}', [
      { idx: 0, start_s: 0, end_s: 1, text: astral },
    ])
    expect([...got]).toHaveLength(160) // measured from the Python: 160 glyphs
    expect(got.length).toBe(320) // and what .slice(0,160) would WRONG-keep: 80
  })

  it('returns "" when nothing mentions the concept, and "—" never leaks in', () => {
    expect(supportSentence('Gaps', FIXTURE_SEGMENTS)).toBe('')
    expect(supportSentence('Touching tail', FIXTURE_SEGMENTS)).toBe('')
    expect(supportSentence('No window', FIXTURE_SEGMENTS)).toBe('')
  })
})

describe('buildTimelineModel — the golden fixture', () => {
  it('measures coverage from the merged union, not the sum of windows', () => {
    // The sum of concept lengths would be 10+14+8+5+3+0+0+5 = 45s (overlap
    // double-counted); the union the Python draws is 38s. 62s duration:
    // the broken concept's start_s stretches the axis past the transcript.
    expect(model.duration).toBe(62)
    expect(model.coveredSeconds).toBe(38)
    // 38/62 in both runtimes produces the same double.
    expect(model.coverage).toBe(38 / 62)
    expect(model.coverage).not.toBe(45 / 62)
  })

  it('prints the caption exactly as the Python did', () => {
    expect(model.captionPlain).toBe(
      '9 concepts · 5 transcript segments · ' +
        '61% of the lecture covered by extracted concepts (38s of 62s).',
    )
    expect(model.captionBold).toBe('61% of the lecture covered')
    expect(model.pctText).toBe('61')
    expect(model.coveredText).toBe('38')
    expect(model.durationText).toBe('62')
  })

  it('sizes the svg by DRAWN bands only (the broken concept draws none)', () => {
    // 78 + 27 * 8 drawn bands — not 9 concepts.
    expect(model.svgHeight).toBe(294)
    expect(model.bands).toHaveLength(8)
  })

  it('draws transcript ticks at every segment start', () => {
    expect(model.ticks).toHaveLength(FIXTURE_SEGMENTS.length)
    MEASURED_TICK_X.forEach((measured, i) => {
      expect(model.ticks[i]?.x).toBeCloseTo(Number(measured), 1)
    })
  })

  it('draws one rect per merged run with the measured geometry and titles', () => {
    expect(model.coveredRects).toHaveLength(4)
    model.coveredRects.forEach((run, i) => {
      expect(run.title).toBe(MEASURED_RUN_TITLES[i])
      expect(run.x).toBeCloseTo(Number(MEASURED_RUN_GEOMETRY[i]?.x), 1)
      expect(run.width).toBeCloseTo(Number(MEASURED_RUN_GEOMETRY[i]?.width), 1)
    })
  })

  it('draws bands in TAUGHT order with the measured geometry', () => {
    // Wavefunction is band #1 (top 58) even though EXPECTATION VALUE starts
    // earlier in time — the input order is the taught order, always.
    const measuredWindows = [
      [10, 25], [18, 32], [32, 40], [40, 45],
      [48, 51], [51, 51], [56, 56], [0, 0],
    ] as const
    model.bands.forEach((band, i) => {
      expect(band.a).toBe(measuredWindows[i]?.[0])
      expect(band.b).toBe(measuredWindows[i]?.[1])
      expect(band.top).toBe(MEASURED_BAND_TOPS[i])
      expect(band.x).toBeCloseTo(Number(MEASURED_BAND_X[i]), 1)
      expect(band.width).toBeCloseTo(Number(MEASURED_BAND_WIDTHS[i]), 1)
      // Python's int(x) truncation, not rounding (161.29 becomes 167, 290.32 -> 296).
      expect(band.labelX).toBe(MEASURED_BAND_LABEL_X[i])
      expect(band.labelY).toBe((MEASURED_BAND_TOPS[i] as number) + 15)
      expect(band.title).toBe(MEASURED_BAND_TITLES[i])
    })
  })

  it('sends band fills through the token ramp with measured ink', () => {
    // The Python's measured hexes for this fixture (#296560 … #654629) are
    // emitted by the same node_fill path — the theme goldens in
    // theme.test.ts pin tokens.ts against Python, so here the ramp's
    // fractions and the ink choice are what is pinned.
    model.bands.forEach((band, i) => {
      const fraction = (i as number) / (FIXTURE_CONCEPTS.length - 1)
      const expectedFill = nodeFill((175 + (8 - 175) * fraction) / 360)
      expect(band.fill).toBe(expectedFill)
      expect(band.ink).toBe(readableOn(expectedFill))
    })
  })

  it('lists every concept as a row, in order, with measured windows', () => {
    expect(model.rows.map((r) => r.index)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9])
    expect(model.rows.map((r) => r.name)).toEqual(
      FIXTURE_CONCEPTS.map((c) => c.name),
    )
    expect(model.rows.map((r) => r.window)).toEqual([
      '10.0 \u2013 25.0s',
      '18.0 \u2013 32.0s',
      '32.0 \u2013 40.0s',
      '40.0 \u2013 45.0s',
      '48.0 \u2013 51.0s',
      '51.0 \u2013 51.0s',
      '56.0 \u2013 56.0s',
      '\u2014',
      '0.0 \u2013 0.0s',
    ])
  })

  it('attaches the measured quiz-evidence sentence per row', () => {
    const byName = new Map(model.rows.map((r) => [r.name, r.support]))
    expect(byName.get('Wavefunction')).toBe(
      'The expectation value of position is the first moment of the wavefunction. two runs collapse here',
    )
    expect(byName.get('EXPECTATION VALUE')).toBe('expectation value')
    expect(byName.get('the spacing')).toBe(
      'Note the spacing: whitespace runs collapse in the support sentence.',
    )
    expect(byName.get('Kurtosis')).toHaveLength(160)
    expect(byName.get('Gaps')).toBe('\u2014')
    expect(byName.get('Br<&>k "x"')).toBe('\u2014')
    expect(byName.get('No window')).toBe('\u2014')
  })

  it('labels the axis 0s / 62s at the measured x', () => {
    expect(model.axisStart).toEqual({ x: 0, text: '0s' })
    expect(model.axisEnd).toEqual({ x: 960, text: '62s' })
  })
})

describe('buildTimelineModel — the empty payload (measured)', () => {
  const empty = buildTimelineModel(null, null, '')

  it('stays honest with nothing to show', () => {
    // Measured from lecture_html([], []): a 1s floor duration, 0% coverage,
    // one 78px-tall drawing with no rects, header only in the table.
    expect(empty.duration).toBe(1)
    expect(empty.coveredSeconds).toBe(0)
    expect(empty.coverage).toBe(0)
    expect(empty.svgHeight).toBe(78)
    expect(empty.ticks).toHaveLength(0)
    expect(empty.coveredRects).toHaveLength(0)
    expect(empty.bands).toHaveLength(0)
    expect(empty.rows).toHaveLength(0)
    expect(empty.captionPlain).toBe(
      '0 concepts · 0 transcript segments · ' +
        '0% of the lecture covered by extracted concepts (0s of 1s).',
    )
    expect(empty.captionBold).toBe('0% of the lecture covered')
    expect(empty.axisEnd).toEqual({ x: 960, text: '1s' })
  })
})
