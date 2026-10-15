/**
 * Rank graph nodes so the important ones survive a readability cut.
 *
 * Ported from `frontend/render.py::graph_importance` on `main`. A course DAG
 * can easily hold 100+ nodes and forcing all of them into one view is
 * unreadable in *any* renderer — a content problem, not a framework one.
 * Concepts like "HAVING", "update" or "GROUP BY" are real rows in the graph
 * but not concepts a learner needs to reason about.
 *
 * Score (higher = keep), exactly as the Python:
 *   - graph degree — a node with several prerequisite links is load-bearing;
 *   - name specificity — a multi-word name ("Conditional Expectation") is a
 *     concept, a single bare token ("update", "filter") usually is not;
 *   - case shape — ALL-CAPS names are overwhelmingly SQL/keyword fragments.
 *
 * ## Fidelity traps (from the port notes — each is a test below)
 *
 * 1. **No `localeCompare`.** Python's `str(a) < str(b)` is a code-point
 *    compare; locale order flips `"a"` against `"B"`. The tiebreak below uses
 *    `<`/`>`, which compare UTF-16 code units — identical to code points for
 *    the BMP, where every real concept name lives.
 * 2. **Split on `/\s+/`, not `' '`.** Python's `str.split()` splits on any
 *    whitespace run (and strips the ends); `"Linear  Regression"` is two words
 *    and `"  spaced   out  "` is two, not four. `filter(Boolean)` reproduces
 *    the stripping, because the empty strings a leading/trailing run produces
 *    are falsy.
 * 3. **Unicode-aware `isalpha`/`isupper`.** Python's `ch.isalpha()` is Unicode
 *    property `L`, not `[A-Za-z]` — and `isupper()` is "cased and uppercase",
 *    so digits never count and `"A1 B2"` (letters A, B, both upper) still takes
 *    the −2.5. The helpers below use `\p{L}` and `\p{Lu}` for the same reason.
 * 4. **`[...name].length`, not `.length`.** Python counts code points, so an
 *    astral character (`💡`) is one, not a surrogate pair. Spread iterates code
 *    points, `.length` counts UTF-16 units.
 *
 * ## One deliberate difference
 *
 * The Python returns `(kept_names, dropped_names)` as **sets** — membership
 * with no order. Here `kept` is in ranked order, because the DAG view draws
 * the kept nodes and the rank *is* the drawing input. Membership is identical;
 * only the container changed, and the test pins both.
 */

export interface RankedGraph {
  /** Kept names, best first. */
  kept: string[]
  /** The rest, in ranked order after `kept`. */
  dropped: string[]
}

/** `str.split()` with no arguments: any whitespace run, ends stripped. */
function wordsOf(name: string): string[] {
  return String(name)
    .split(/\s+/)
    .filter((w) => w.length > 0)
}

/** `len(str)` — code points, so an astral character counts once. */
function codePoints(name: string): number {
  return [...String(name)].length
}

/** `ch.isalpha()` — Unicode letter, not ASCII. */
function lettersOf(name: string): string[] {
  return [...String(name)].filter((ch) => /\p{L}/u.test(ch))
}

/** `ch.isupper()` — cased and uppercase (digits are never "upper"). */
function isUpper(ch: string): boolean {
  return /\p{Lu}/u.test(ch)
}

/**
 * The Python's `score()`, with the degree passed in. Exact constants:
 * +2.0 for two or more words, +1.0 for length ≥ 18, −2.5 for all-uppercase
 * letters, −1.0 for length ≤ 6.
 */
export function scoreConcept(name: string, degree: number): number {
  const text = String(name)
  let s = degree * 1.0
  if (wordsOf(text).length >= 2) s += 2.0
  if (codePoints(text) >= 18) s += 1.0
  const letters = lettersOf(text)
  if (letters.length > 0 && letters.every(isUpper)) s -= 2.5
  if (codePoints(text) <= 6) s -= 1.0
  return s
}

export interface RankEdge {
  source?: string | null
  target?: string | null
}

/** Degree over both ends; falsy sides (`""`, `null`) contribute nothing. */
function degreesOf(edges: readonly RankEdge[] | null | undefined): Map<string, number> {
  const degree = new Map<string, number>()
  for (const e of edges ?? []) {
    for (const side of [e?.source, e?.target] as const) {
      if (side) degree.set(side, (degree.get(side) ?? 0) + 1)
    }
  }
  return degree
}

/**
 * Ranked `(kept, dropped)` for a node limit.
 *
 * Sort is score-descending with a code-point name tiebreak — the Python's
 * `sorted(nodes, key=lambda n: (-score(n), str(n)))`. A falsy `limit`
 * (0, as the Python treats it) keeps everything.
 */
export function rankConcepts(
  nodes: readonly string[] | null | undefined,
  edges: readonly RankEdge[] | null | undefined,
  limit = 40,
): RankedGraph {
  const degree = degreesOf(edges)
  const ranked = [...(nodes ?? [])].sort((a, b) => {
    const byScore =
      scoreConcept(b, degree.get(b) ?? 0) - scoreConcept(a, degree.get(a) ?? 0)
    if (byScore !== 0) return byScore
    const sa = String(a)
    const sb = String(b)
    return sa < sb ? -1 : sa > sb ? 1 : 0
  })
  if (limit && ranked.length > limit) {
    return { kept: ranked.slice(0, limit), dropped: ranked.slice(limit) }
  }
  return { kept: ranked, dropped: [] }
}
