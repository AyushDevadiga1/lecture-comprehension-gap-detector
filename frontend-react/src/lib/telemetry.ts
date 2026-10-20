import type { CourseGraphOut, CourseStats } from '../api/types'

/**
 * The three subtle numbers behind the faculty telemetry strip, as pure
 * functions so they can be unit-tested without rendering.
 *
 * - **Root concepts** counts nodes with in-degree 0, not
 *   `topological_order.length` — the latter is the concept count, a real bug
 *   fixed in `27fed3c`. With no edges, every node is effectively a root.
 * - **Gaps tracked** counts concepts whose wrong-answer rate exceeds 30%, the
 *   same threshold the heatmap's colour ramp uses, so the card and the bars
 *   agree on what "at risk" means.
 */
export function rootConceptCount(graph: CourseGraphOut | null): number {
  if (!graph) return 0
  if (graph.edges.length === 0) return graph.node_count
  const hasIncoming = new Set(graph.edges.map((e) => e.target))
  return graph.nodes.filter((n) => !hasIncoming.has(n)).length
}

export function gapCount(stats: CourseStats | null): number {
  if (!stats) return 0
  return stats.heatmap.filter((h) => h.rate > 0.3).length
}

export function averageDivergence(stats: CourseStats | null): string {
  if (!stats || stats.divergence.length === 0) return '0.0'
  const avg = stats.divergence.reduce((acc, d) => acc + d.gap, 0) / stats.divergence.length
  return avg.toFixed(1)
}
