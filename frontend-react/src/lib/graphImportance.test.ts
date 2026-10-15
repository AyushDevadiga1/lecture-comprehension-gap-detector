import { describe, expect, it } from 'vitest'
import { rankConcepts, scoreConcept } from './graphImportance'

/**
 * Fidelity tests for the `graph_importance` port.
 *
 * The golden values below are measured from the Python, not derived by hand:
 * the fixture ran through `frontend/render.py::graph_importance` on `main`
 * and kept exactly
 * `Conditional Expectation, GROUP BY, Linear␣␣Regression, Slope, update,
 *  x×18` at limit 6, dropping `A1 B2, B, HAVING, INNER JOIN, a, filter`.
 * If this file and the Python ever disagree, these tables say which one moved.
 *
 * Each of the four port traps has its own test, named for the trap.
 */

const EDGES = [
  { source: 'Slope', target: 'Linear  Regression' },
  { source: 'update', target: 'Slope' },
  // Falsy sides contribute no degree — the Python guards with `if nm`.
  { source: '', target: 'Slope' },
  { source: 'HAVING', target: null },
]

const NAMES = [
  'Conditional Expectation',
  'HAVING',
  'update',
  'GROUP BY',
  'A1 B2',
  'Slope',
  'a',
  'B',
  'Linear  Regression',
  'xxxxxxxxxxxxxxxxxx',
  'INNER JOIN',
  'filter',
]

describe('scoreConcept — the exact arithmetic', () => {
  it.each([
    // [name, degree, score] — every row measured from the Python.
    ['Linear  Regression', 1, 4.0],
    ['Conditional Expectation', 0, 3.0],
    ['Slope', 2, 1.0],
    ['xxxxxxxxxxxxxxxxxx', 0, 1.0],
    ['update', 1, 0.0],
    ['GROUP BY', 0, -0.5],
    ['INNER JOIN', 0, -0.5],
    ['a', 0, -1.0],
    ['filter', 0, -1.0],
    ['A1 B2', 0, -1.5],
    ['HAVING', 1, -2.5],
    ['B', 0, -3.5],
  ])('%s at degree %i scores %f', (name, degree, score) => {
    expect(scoreConcept(name, degree)).toBe(score)
  })
})

describe('rankConcepts — the golden fixture', () => {
  it('keeps the same six the Python keeps at limit 6', () => {
    const { kept, dropped } = rankConcepts(NAMES, EDGES, 6)
    expect(new Set(kept)).toEqual(
      new Set([
        'Conditional Expectation',
        'GROUP BY',
        'Linear  Regression',
        'Slope',
        'update',
        'xxxxxxxxxxxxxxxxxx',
      ]),
    )
    expect(new Set(dropped)).toEqual(
      new Set(['A1 B2', 'B', 'HAVING', 'INNER JOIN', 'a', 'filter']),
    )
  })

  it('keeps ranked order, best first', () => {
    const { kept } = rankConcepts(NAMES, EDGES, 6)
    // 4.0, 3.0, then the 1.0 pair in code-point order, then 0.0, then −0.5.
    expect(kept[0]).toBe('Linear  Regression')
    expect(kept[1]).toBe('Conditional Expectation')
    expect(kept.slice(2, 4)).toEqual(['Slope', 'xxxxxxxxxxxxxxxxxx'])
  })

  it('a falsy limit keeps everything, like the Python', () => {
    const { kept, dropped } = rankConcepts(NAMES, EDGES, 0)
    expect(kept).toHaveLength(NAMES.length)
    expect(dropped).toEqual([])
  })

  it('a limit above the size keeps everything', () => {
    const { kept, dropped } = rankConcepts(['a', 'B'], [], 99)
    expect(kept).toHaveLength(2)
    expect(dropped).toEqual([])
  })

  it('empty and missing inputs keep nothing and drop nothing', () => {
    expect(rankConcepts([], [])).toEqual({ kept: [], dropped: [] })
    expect(rankConcepts(null, null)).toEqual({ kept: [], dropped: [] })
    expect(rankConcepts(undefined, undefined)).toEqual({ kept: [], dropped: [] })
  })
})

describe('the four port traps', () => {
  it('trap 1: the tiebreak is code-point order, not locale order', () => {
    // 'z' is 122, 'ä' is 228 — code points put z first, and both score −1.0
    // so the tiebreak is what orders them. A locale-aware compare sorts 'ä'
    // with 'a' and would put it first, silently recolouring and reordering.
    // (The earlier draft of this test used 'a' vs 'B', which score −1.0 and
    // −3.5 — no tie at all, so it proved nothing about the tiebreak.)
    const { kept } = rankConcepts(['ä', 'z'], [], 5)
    expect(kept).toEqual(['z', 'ä'])
  })

  it('trap 2: split on any whitespace run, ends stripped', () => {
    // A double space is still two words (the +2.0 fires for the fixture's
    // 'Linear  Regression'); leading/trailing runs add no phantom words.
    expect(scoreConcept('Linear  Regression', 0)).toBe(3.0)
    expect(scoreConcept('  spaced   out  ', 0)).toBe(2.0)
  })

  it('trap 3: isalpha/isupper are Unicode properties', () => {
    // Digits never count as letters, so "A1 B2" is judged on A and B alone —
    // both uppercase, so the −2.5 fires despite the digits and the space.
    expect(scoreConcept('A1 B2', 0)).toBe(-1.5)
    // A bare digit string has no letters at all: only the short-name penalty.
    expect(scoreConcept('123', 0)).toBe(-1.0)
  })

  it('trap 4: length counts code points, not UTF-16 units', () => {
    // 'A💡B' is 3 code points but 4 UTF-16 units. `.length` says 4 (no
    // short-name penalty either way here); spread says 3. The observable
    // difference is at the ≥18 boundary, so pin it there instead.
    const astral = 'x'.repeat(17) + '💡'
    expect([...astral].length).toBe(18)
    expect(astral.length).toBe(19)
    expect(scoreConcept(astral, 0)).toBe(1.0)
  })
})
