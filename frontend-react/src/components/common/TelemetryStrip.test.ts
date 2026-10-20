import { describe, expect, it } from 'vitest'
import type { CourseGraphOut, CourseStats } from '../../api/types'
import { averageDivergence, gapCount, rootConceptCount } from '../../lib/telemetry'

/**
 * The two subtle numbers in the telemetry strip, pinned so the 27fed3c bug
 * (root count = topological_order.length) cannot come back.
 */

function graph(edges: Array<[string, string]>, nodes: string[]): CourseGraphOut {
  return {
    course_id: 'ml',
    nodes,
    edges: edges.map(([source, target], i) => ({
      source,
      target,
      confidence: 0.9,
      source_method: 'spoken',
      evidence: `e${i}`,
    })),
    node_count: nodes.length,
    edge_count: edges.length,
    is_dag: true,
    topological_order: nodes,
  }
}

describe('rootConceptCount', () => {
  it('counts nodes with in-degree 0, not topological_order.length', () => {
    // a → b → c: only "a" is a root. topological_order.length would say 3.
    const g = graph(
      [
        ['a', 'b'],
        ['b', 'c'],
      ],
      ['a', 'b', 'c'],
    )
    expect(rootConceptCount(g)).toBe(1)
  })

  it('treats every node as a root when there are no edges', () => {
    const g = graph([], ['a', 'b', 'c'])
    expect(rootConceptCount(g)).toBe(3)
  })

  it('counts multiple roots in a diamond', () => {
    // a → b, a → c, b → d, c → d: roots are a only... wait, a is the sole root.
    // Use a forest: a → b, c → d — two roots.
    const g = graph(
      [
        ['a', 'b'],
        ['c', 'd'],
      ],
      ['a', 'b', 'c', 'd'],
    )
    expect(rootConceptCount(g)).toBe(2)
  })

  it('returns 0 for a null graph', () => {
    expect(rootConceptCount(null)).toBe(0)
  })
})

describe('gapCount', () => {
  it('counts concepts whose rate exceeds 30%', () => {
    const stats: CourseStats = {
      course_id: 'ml',
      heatmap: [
        { concept: 'a', wrong: 5, attempts: 10, rate: 0.5 },
        { concept: 'b', wrong: 2, attempts: 10, rate: 0.2 },
        { concept: 'c', wrong: 4, attempts: 10, rate: 0.4 },
      ],
      divergence: [],
      taught_order: [],
      learned_order: [],
    }
    expect(gapCount(stats)).toBe(2)
  })

  it('uses a strict threshold — exactly 30% is not a gap', () => {
    const stats: CourseStats = {
      course_id: 'ml',
      heatmap: [{ concept: 'a', wrong: 3, attempts: 10, rate: 0.3 }],
      divergence: [],
      taught_order: [],
      learned_order: [],
    }
    expect(gapCount(stats)).toBe(0)
  })

  it('returns 0 for null stats', () => {
    expect(gapCount(null)).toBe(0)
  })
})

describe('averageDivergence', () => {
  it('averages the gap column', () => {
    const stats: CourseStats = {
      course_id: 'ml',
      heatmap: [],
      divergence: [
        { concept: 'a', gap: 2 },
        { concept: 'b', gap: 4 },
      ],
      taught_order: [],
      learned_order: [],
    }
    expect(averageDivergence(stats)).toBe('3.0')
  })

  it('returns 0.0 when there is no divergence data', () => {
    const stats: CourseStats = { course_id: 'ml', heatmap: [], divergence: [], taught_order: [], learned_order: [] }
    expect(averageDivergence(stats)).toBe('0.0')
    expect(averageDivergence(null)).toBe('0.0')
  })
})
