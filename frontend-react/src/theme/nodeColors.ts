/**
 * Node colours for the DAG and the timeline.
 *
 * Ported from `frontend/render.py::node_colors`. Two modes, and the decision
 * table below is the contract:
 *
 * | mode      | rank     | total     | result               |
 * |-----------|----------|-----------|----------------------|
 * | `order`   | not null | truthy >1 | order ramp on `rank` |
 * | `order`   | not null | 0/1/null  | identity hash        |
 * | `order`   | null     | anything  | identity hash        |
 * | anything else, including a typo | | | identity hash      |
 *
 * So `nodeColors('X')` with defaults is an *identity* colour, not an error, and
 * any unrecognised `colorBy` value silently means identity. That is the Python's
 * behaviour and is preserved rather than tightened: a panel passing a bad value
 * gets a stable, legible colour instead of an exception mid-render.
 *
 * Both modes agree on lightness (`palette.node_light`) and differ only in how
 * hue and saturation are chosen, so every node keeps the same visual weight.
 */

import { sha256 } from '@noble/hashes/sha2.js'
import { nodePair } from './tokens'

/**
 * Order ramp: teal at rank 0 to coral at the last rank, in *degrees*. Divided by
 * 360 at the use site because `hsl` takes turns, like Python.
 */
const RAMP_START_DEG = 175.0
const RAMP_END_DEG = 8.0

/** Identity saturation: `0.45 + byte/255 * 0.18`, i.e. within [0.45, 0.6294). */
const IDENTITY_SAT_FLOOR = 0.45
const IDENTITY_SAT_SPAN = 0.18

export type ColourMode = 'order' | 'identity'

/**
 * The digest bytes the identity mode reads.
 *
 * Only bytes 0 and 2 of the 32-byte SHA-256 are used; the rest are ignored. The
 * name is UTF-8 encoded, so a name with a fullwidth pipe works.
 *
 * `crypto.subtle` cannot be used here: it is async and needs a secure context,
 * and `nodeFill` is called during render. `@noble/hashes` is a synchronous
 * implementation whose output is byte-identical to Python's `hashlib` -- the
 * golden tables in `theme.test.ts` are measured from the Python and would fail
 * if this were substituted.
 */
function digest(name: string): Uint8Array {
  return sha256(new TextEncoder().encode(String(name)))
}

function orderHue(rank: number, total: number): number {
  const frac = Math.min(Math.max(rank / (total - 1), 0), 1)
  return (RAMP_START_DEG + (RAMP_END_DEG - RAMP_START_DEG) * frac) / 360
}

function identityHueAndSat(name: string): { hue: number; sat: number } {
  const d = digest(name)
  return {
    hue: d[0]! / 255,
    sat: IDENTITY_SAT_FLOOR + (d[2]! / 255) * IDENTITY_SAT_SPAN,
  }
}

/**
 * The fill and the ink that is legible on it, for one node.
 *
 * `rank` is 0-based within the learner order and `total` is the length of that
 * order, not the number of nodes actually drawn, so a significance filter does
 * not recolour the graph.
 */
export function nodeColors(
  name: string,
  rank?: number | null,
  total?: number | null,
  mode: ColourMode | string = 'order',
  base?: string | null,
): [string, string] {
  const b = base ?? undefined
  const useOrder = mode === 'order' && rank != null && !!total && total > 1
  if (useOrder) return nodePair(orderHue(rank, total), b)
  const { hue, sat } = identityHueAndSat(name)
  return nodePair(hue, b, sat)
}
