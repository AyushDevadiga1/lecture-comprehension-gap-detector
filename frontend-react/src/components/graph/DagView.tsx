import React from 'react'
import ReactFlow, { Background, Handle, MarkerType, MiniMap, Position } from 'reactflow'
import type { Edge as FlowEdge, Node as FlowNode, NodeProps, ReactFlowInstance } from 'reactflow'
import 'reactflow/dist/style.css'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControl,
  InputLabel,
  ListItemText,
  MenuItem,
  OutlinedInput,
  Select,
  Slider,
  TextField,
  Typography,
} from '@mui/material'
import type { SelectChangeEvent } from '@mui/material/Select'
import type { CourseGraphOut, GraphEdgeOut } from '../../api/types'
import { rankConcepts } from '../../lib/graphImportance'
import { nodeColors } from '../../theme/nodeColors'
import { tint, token } from '../../theme/alpha'

/**
 * The course prerequisite DAG, drawn with reactflow.
 *
 * Ports `frontend/panels/graph.py` (controls, counts, study sequence) onto the
 * data layer ported from `frontend/render.py` (`graphImportance`,
 * `nodeColors`). Until this file, the graph payload reached the UI but was
 * rendered as an edges table — the data was plumbed, the drawing skipped.
 *
 * What is ported, behaviour-for-behaviour:
 *   - significance ranking with the node-limit cut (`READABLE_ALL` /
 *     `DEFAULT_LIMIT`, slider 5..max in steps of 5);
 *   - colour-by learner order vs concept identity, via the same `nodeColors`;
 *   - edge-type filtering over the methods actually present;
 *   - the counts line (total · shown · acyclic/cyclic) and the dropped-count
 *     caption;
 *   - the learner-order study sequence in a bounded scroll box;
 *   - a min-confidence cut for links (from the approved mock): links below
 *     the slider are hidden, not faded, and the "Links drawn" count follows;
 *     node layout ignores the cut so the graph does not jump while sliding.
 *
 * What is new, because an SVG layout does not transfer to a canvas:
 *   - positions come from a deterministic layered layout (depth = longest
 *     prerequisite chain, guarded against cycles; order within a layer follows
 *     the topological order), not from `dag_svg`;
 *   - hover evidence becomes **click evidence**: selecting a node lists its
 *     incident edges with confidence, method and recorded evidence;
 *   - selecting also focuses the canvas: unrelated nodes dim to 0.35 and the
 *     selected concept's own links widen in accent, so the click answers
 *     "what does this depend on" visually, not only in the panel;
 *   - edges carry arrowheads (direction was unreadable without them);
 *   - a find-concept box selects and centres the first case-insensitive
 *     substring match among shown nodes — the only way to locate one node
 *     in 150 — and says plainly when matches are hidden by the limit cut;
 *   - pan/zoom are the canvas's own (drag to pan, scroll to zoom, fit on load),
 *     so there is no zoom slider and no `<Controls>` chrome to theme; a
 *     minimap (nodes in their own fills) plus an explicit Reset view button
 *     cover spatial context and the way back, which is the whole of the
 *     chrome this view needs.
 *
 * Colours: node fills and ink come from `nodeColors` (token-derived at
 * runtime, never literals — the colour guard only sees the variable, which is
 * the sanctioned shape); chrome is MUI slots and `var(--lgc-*)`. The stock
 * reactflow stylesheet is intentionally unthemed for this pass.
 */

export const READABLE_ALL = 60
export const DEFAULT_LIMIT = 40

export type ColourBy = 'order' | 'identity'

export interface DagViewProps {
  graph: CourseGraphOut
  /** Disambiguates control ids when two views share a page. */
  idPrefix?: string
}

interface ConceptNodeData {
  label: string
  fill: string
  ink: string
  rankLabel: string | null
  pressed: boolean
  select: () => void
}

/**
 * One concept: order badge + label on its measured fill/ink.
 *
 * The root is the node's *only* interactive element. React Flow wraps every
 * node in its own positioned div and gives that wrapper `role="button"` +
 * keyboard handling whenever the node is selectable *or* focusable — so the
 * nodes below set both to false, and this root carries the role, the name, the
 * keyboard handling and the pressed state instead. Otherwise every concept
 * announces twice (once from raw content as "9Slope", once from here), and
 * role queries match the wrapper as well as the root.
 *
 * `disableKeyboardA11y` on the canvas goes with this: React Flow's
 * instructions ("use the arrow keys to move the node around") describe
 * keyboard behaviour these nodes do not have, so they must not be announced.
 */
function ConceptNode({ data }: NodeProps<ConceptNodeData>) {
  return (
    <Box
      tabIndex={0}
      role="button"
      aria-pressed={data.pressed}
      aria-label={data.rankLabel ? `${data.label}, learner step ${data.rankLabel}` : data.label}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          data.select()
        }
      }}
      sx={{
        backgroundColor: data.fill,
        color: data.ink,
        borderRadius: 1.5,
        px: 1,
        py: 0.6,
        minWidth: 130,
        maxWidth: 150,
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        border: '1px solid',
        borderColor: tint('text', 8),
        cursor: 'pointer',
        boxShadow: data.pressed ? '0 0 0 2px var(--lgc-info)' : 'none',
        '&:focus-visible': {
          outline: '2px solid',
          outlineColor: 'info.main',
        },
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      {data.rankLabel && (
        <Box
          component="span"
          sx={{
            fontSize: '0.7rem',
            fontWeight: 600,
            borderRadius: '50%',
            width: 22,
            height: 22,
            flexShrink: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          {data.rankLabel}
        </Box>
      )}
      {/* Ellipsis, never overflow: a 60-char concept name must not stretch
          its node and break the fixed row pitch. The full name survives in
          `title` and in the node's aria-label. flex:1 + minWidth:0 is what
          lets text truncate inside a flex row. */}
      <Typography
        variant="body2"
        title={data.label}
        sx={{
          fontWeight: 600,
          lineHeight: 1.25,
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {data.label}
      </Typography>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </Box>
  )
}

// Module scope (not exported): reactflow warns on an inline `nodeTypes` object
// because a fresh identity remounts every node on each render.
const nodeTypes = { concept: ConceptNode }

/** One incident edge: endpoints, method, confidence, recorded evidence. */
const EdgeRow: React.FC<{ edge: GraphEdgeOut }> = ({ edge: e }) => (
  <Box sx={{ py: 1, borderTop: '1px solid', borderColor: 'divider' }}>
    <Typography variant="body2" sx={{ fontWeight: 600 }}>
      {e.source} → {e.target}
    </Typography>
    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5, flexWrap: 'wrap' }}>
      <Chip
        size="small"
        label={
          e.source_method === 'transcript' ? 'spoken in lecture' : 'classifier-inferred'
        }
        color={e.source_method === 'transcript' ? 'info' : 'default'}
        variant="outlined"
      />
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        confidence {(e.confidence ?? 0).toFixed(2)}
      </Typography>
    </Box>
    {e.evidence && (
      <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
        “{e.evidence}”
      </Typography>
    )}
  </Box>
)

const X_GAP = 200
const Y_GAP = 110

const NO_NODES: string[] = []
const NO_EDGES: GraphEdgeOut[] = []
const NO_ORDER: string[] = []

/**
 * Depth = longest prerequisite chain above the node. Cycles fall back to the
 * shallowest consistent depth via the visiting guard, so a non-DAG still draws
 * instead of recursing forever.
 */
function layoutLayers(
  kept: string[],
  edges: readonly GraphEdgeOut[],
): Map<string, { x: number; y: number }> {
  const keptSet = new Set(kept)
  const parents = new Map<string, string[]>()
  for (const e of edges) {
    if (keptSet.has(e.source) && keptSet.has(e.target)) {
      const list = parents.get(e.target) ?? []
      list.push(e.source)
      parents.set(e.target, list)
    }
  }
  const memo = new Map<string, number>()
  const depth = (name: string, visiting: Set<string>): number => {
    const known = memo.get(name)
    if (known !== undefined) return known
    if (visiting.has(name)) return 0
    visiting.add(name)
    let d = 0
    for (const p of parents.get(name) ?? []) {
      d = Math.max(d, depth(p, visiting) + 1)
    }
    visiting.delete(name)
    memo.set(name, d)
    return d
  }
  const byDepth = new Map<number, string[]>()
  for (const n of kept) {
    const d = depth(n, new Set())
    const list = byDepth.get(d) ?? []
    list.push(n)
    byDepth.set(d, list)
  }
  const positions = new Map<string, { x: number; y: number }>()
  for (const [d, names] of [...byDepth.entries()].sort((a, b) => a[0] - b[0])) {
    names.forEach((n, i) => positions.set(n, { x: i * X_GAP, y: d * Y_GAP }))
  }
  return positions
}

export const DagView: React.FC<DagViewProps> = ({ graph, idPrefix = 'dag' }) => {
  // Stable empties: `graph.nodes ?? []` would allocate a fresh array on every
  // render, churning every useMemo below (the exhaustive-deps rule flags
  // exactly this). Module-level singletons keep the identities stable.
  const nodes = graph.nodes ?? NO_NODES
  const edges = graph.edges ?? NO_EDGES
  const order = graph.topological_order ?? NO_ORDER

  const [colorBy, setColorBy] = React.useState<ColourBy>('order')
  const [methods, setMethods] = React.useState<string[] | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [query, setQuery] = React.useState('')
  const [searchNote, setSearchNote] = React.useState<string | null>(null)
  // The canvas instance, for the reset-view affordance only. Captured via
  // onInit rather than a ReactFlowProvider so this component stays
  // self-contained: providers are app-level decisions (see AppProviders), and
  // a graph view should not impose one on its host page.
  const [flow, setFlow] = React.useState<ReactFlowInstance | null>(null)

  const methodsPresent = React.useMemo(() => {
    const found = sortedUnique(edges.map((e) => e.source_method || 'classifier'))
    return found.length ? found : ['classifier']
  }, [edges])
  const wanted = methods ?? methodsPresent

  const [limit, setLimit] = React.useState<number>(() =>
    nodes.length <= READABLE_ALL ? nodes.length : DEFAULT_LIMIT,
  )

  /**
   * Minimum edge confidence, in percent. 0% (the default) draws every link,
   * so the shipped view is unchanged. Below-threshold links are HIDDEN, not
   * dimmed: the counts line says "drawn", and a fade would make it lie.
   * Node positions keep using the confidence-unfiltered set, so sliding does
   * not shuffle the layout under the pointer — only the links come and go.
   */
  const [minConfidence, setMinConfidence] = React.useState(0)

  const { kept, dropped } = React.useMemo(
    () => rankConcepts(nodes, edges, limit),
    [nodes, edges, limit],
  )

  const rankOf = React.useMemo(() => {
    const index = new Map(order.map((name, i) => [name, i] as const))
    return (name: string): number | null => index.get(name) ?? null
  }, [order])

  const keptSet = React.useMemo(() => new Set(kept), [kept])

  /**
   * The selection the canvas can actually show. State stays raw — filtering
   * must never destroy it, or raising the slider back would lose the
   * reader's place — but everything *displayed* (focus dimming, evidence,
   * pressed ring) reads this: a selected concept that a filter cut is
   * invisible, so showing its panel would be an evidence card for a ghost.
   */
  const shownSelected =
    selected != null && keptSet.has(selected) ? selected : null

  /**
   * Focus mode: the selected concept plus everything one link away, or null
   * when nothing is selected. Nodes outside the set dim to 0.35 and their
   * edges thin out, so a click answers "what does this depend on" visually
   * instead of only in the evidence panel below.
   */
  const focusSet = React.useMemo(() => {
    if (shownSelected == null) return null
    const set = new Set<string>([shownSelected])
    for (const e of edges) {
      if (e.source === shownSelected && keptSet.has(e.target)) set.add(e.target)
      if (e.target === shownSelected && keptSet.has(e.source)) set.add(e.source)
    }
    return set
  }, [shownSelected, edges, keptSet])
  const shownEdges = React.useMemo(
    () =>
      edges.filter(
        (e) =>
          keptSet.has(e.source) &&
          keptSet.has(e.target) &&
          wanted.includes(e.source_method || 'classifier'),
      ),
    [edges, keptSet, wanted],
  )

  const positions = React.useMemo(
    () => layoutLayers(kept, shownEdges),
    [kept, shownEdges],
  )

  /**
   * The confidence cut. "Minimum" is inclusive: an edge at exactly the slider
   * value draws (the mock's filter, and what "min" should mean). The epsilon
   * only absorbs float noise from `0.7 * 100`-style arithmetic, so a 70% edge
   * is not dropped by a 70% floor.
   */
  const drawnEdges = React.useMemo(
    () =>
      minConfidence <= 0
        ? shownEdges
        : shownEdges.filter(
            (e) => (e.confidence ?? 0) >= minConfidence / 100 - 1e-9,
          ),
    [shownEdges, minConfidence],
  )
  const hiddenByConfidence = shownEdges.length - drawnEdges.length

  const flowNodes: FlowNode<ConceptNodeData>[] = React.useMemo(
    () =>
      kept.map((name) => {
        const rank = rankOf(name)
        const [fill, ink] = nodeColors(name, rank, order.length || null, colorBy)
        const pos = positions.get(name) ?? { x: 0, y: 0 }
        return {
          id: name,
          type: 'concept',
          // Selection is owned here (`selected` + onNodeClick), never by the
          // canvas: a selectable *or focusable* node gets a second role=button
          // wrapper from React Flow itself (see ConceptNode), and every
          // concept would announce twice.
          selectable: false,
          focusable: false,
          position: pos,
          // Focus mode lives here rather than in CSS: opacity follows the
          // focus set computed above, so unrelated concepts recede the
          // moment one is selected.
          style: { opacity: focusSet == null || focusSet.has(name) ? 1 : 0.35 },
          data: {
            label: name,
            fill,
            ink,
            rankLabel: rank == null ? null : String(rank + 1),
            pressed: shownSelected === name,
            select: () => setSelected((cur) => (cur === name ? null : name)),
          },
        }
      }),
    [kept, rankOf, order.length, colorBy, positions, shownSelected, focusSet],
  )

  const flowEdges: FlowEdge[] = React.useMemo(
    () =>
      drawnEdges.map((e, i) => {
        // The selected concept's own links read first: accent, wider, with a
        // matching head. Everything else stays the quiet graph edge.
        const hot =
          selected != null && (e.source === selected || e.target === selected)
        const stroke = hot ? token('accent') : token('graph_edge')
        return {
          id: `${e.source}→${e.target}#${i}`,
          source: e.source,
          target: e.target,
          // Decorative paths: no click behaviour reads them, so they must not
          // be buttons. (Focusable edges get role=button plus an auto label.)
          focusable: false,
          style: { stroke, strokeWidth: hot ? 2.5 : 1 },
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        }
      }),
    [drawnEdges, selected],
  )

  const drawnCount = drawnEdges.length

  const incident = React.useMemo(() => {
    if (shownSelected == null) return []
    return edges.filter((e) => e.source === shownSelected || e.target === shownSelected)
  }, [edges, shownSelected])

  /**
   * Both directions, separately. An edge A → B means "A first": for the
   * selected concept X, the `target === X` rows are what X *needs first* and
   * the `source === X` rows are what X *unlocks*. The flat list this replaces
   * answered "connected to what" but not "study which first" — which is the
   * question the panel exists for. (A self-loop lands in both groups; the
   * backend should not emit them, and showing one twice is more honest than
   * hiding it.)
   */
  const needsFirst = React.useMemo(
    () => incident.filter((e) => e.target === shownSelected),
    [incident, shownSelected],
  )
  const unlocks = React.useMemo(
    () => incident.filter((e) => e.source === shownSelected),
    [incident, shownSelected],
  )

  /**
   * Find-concept: first case-insensitive substring match among the *shown*
   * nodes, selected and centred. Scoped to shown nodes on purpose — matching
   * a hidden concept and silently rewriting the limit would surprise; the
   * note says exactly where to look instead.
   */
  const runSearch = (e: React.FormEvent) => {
    e.preventDefault()
    const q = query.trim().toLowerCase()
    if (!q) {
      setSearchNote(null)
      return
    }
    const hits = kept.filter((n) => n.toLowerCase().includes(q))
    if (hits.length === 0) {
      const hiddenHits = nodes.filter(
        (n) => n.toLowerCase().includes(q) && !keptSet.has(n),
      )
      setSelected(null)
      setSearchNote(
        hiddenHits.length > 0
          ? `"${query.trim()}" matches ${hiddenHits.length} hidden concept(s) — raise Concepts shown.`
          : `No concept matches "${query.trim()}".`,
      )
      return
    }
    const pick = hits[0]!
    setSelected(pick)
    setSearchNote(
      hits.length > 1
        ? `${hits.length} matches — showing ${pick}.`
        : null,
    )
    const pos = positions.get(pick)
    if (pos) flow?.setCenter(pos.x + 90, pos.y + 28, { zoom: 1.1, duration: 300 })
  }

  if (nodes.length === 0) {
    return (
      <Alert severity="info">
        This course has no graph yet. Use &lsquo;Extract concepts + build
        graph&rsquo; on a ready lecture first.
      </Alert>
    )
  }

  const sliderMax = Math.max(nodes.length, 5)

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Controls — the Python's four, plus the mock's confidence filter. */}
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <FormControl size="small" sx={{ minWidth: 220 }}>
          <InputLabel id={`${idPrefix}-color-label`}>Colour by</InputLabel>
          <Select
            labelId={`${idPrefix}-color-label`}
            value={colorBy}
            label="Colour by"
            onChange={(e) => setColorBy(e.target.value as ColourBy)}
          >
            <MenuItem value="order">Learner order (first → last)</MenuItem>
            <MenuItem value="identity">Concept identity</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id={`${idPrefix}-methods-label`}>Edge types</InputLabel>
          <Select
            labelId={`${idPrefix}-methods-label`}
            multiple
            value={wanted}
            label="Edge types"
            input={<OutlinedInput label="Edge types" />}
            renderValue={(list) => (list as string[]).join(', ')}
            onChange={(e: SelectChangeEvent<string[]>) => {
              const value = e.target.value
              setMethods(typeof value === 'string' ? value.split(',') : value)
            }}
          >
            {methodsPresent.map((m) => (
              <MenuItem key={m} value={m}>
                <Checkbox checked={wanted.includes(m)} size="small" />
                <ListItemText primary={m === 'transcript' ? 'spoken transcript' : m} />
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Box sx={{ minWidth: 200 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Min confidence {minConfidence}%
          </Typography>
          <Slider
            aria-label="Min confidence"
            value={minConfidence}
            min={0}
            max={100}
            step={5}
            valueLabelDisplay="auto"
            valueLabelFormat={(v) => `${v}%`}
            onChange={(_, v) => setMinConfidence(v as number)}
          />
        </Box>

        <Box sx={{ minWidth: 220 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Concepts shown
          </Typography>
          <Slider
            aria-label="Concepts shown"
            value={limit}
            min={5}
            max={sliderMax}
            step={5}
            valueLabelDisplay="auto"
            onChange={(_, v) => setLimit(v as number)}
          />
        </Box>

        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          Links drawn {drawnCount} / {edges.length}
        </Typography>

        {/* Find-concept: the only way to locate one node in 150. */}
        <Box
          component="form"
          onSubmit={runSearch}
          sx={{ display: 'flex', gap: 1, alignItems: 'center' }}
        >
          <TextField
            size="small"
            label="Find concept"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            sx={{ width: 200 }}
          />
          <Button size="small" variant="outlined" type="submit">
            Go
          </Button>
        </Box>

        {/* The way back from an arbitrary pan/zoom. fitView is the same
            framing the canvas loads with, so reset means "show me the graph
            as it opened" — discoverable, unlike a gesture. */}
        <Button
          size="small"
          variant="outlined"
          onClick={() => flow?.fitView({ padding: 0.2 })}
        >
          Reset view
        </Button>
      </Box>

      {/* Legend: what the badges, arrows and dimming mean. */}
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        Badge = learner step · arrow = prerequisite link · click a concept for
        its links and evidence · selecting dims everything unrelated.
      </Typography>
      {searchNote && (
        <Typography variant="caption" role="status" sx={{ color: 'text.secondary', mt: -1 }}>
          {searchNote}
        </Typography>
      )}

      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {graph.node_count} concepts in total · {kept.length} shown ·{' '}
        {graph.is_dag ? 'acyclic' : 'contains cycles'}
      </Typography>
      {dropped.length > 0 && (
        <Typography variant="caption" sx={{ color: 'text.secondary', mt: -1 }}>
          {dropped.length} lower-significance concept(s) hidden to keep this
          readable. Raise the slider to include them.
        </Typography>
      )}
      {hiddenByConfidence > 0 && (
        <Typography variant="caption" sx={{ color: 'text.secondary', mt: -1 }}>
          {hiddenByConfidence} lower-confidence link(s) hidden below{' '}
          {minConfidence}%. Lower the Min confidence slider to include them.
        </Typography>
      )}

      {/* Canvas. Pan by dragging, zoom by scrolling; fits on load. */}
      <Box
        aria-label="Course prerequisite graph"
        sx={{
          height: 500,
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: 2,
          backgroundColor: 'background.paper',
          overflow: 'hidden',
        }}
      >
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          onInit={setFlow}
          onNodeClick={(_, node) =>
            setSelected((cur) => (cur === node.id ? null : node.id))
          }
          onPaneClick={() => setSelected(null)}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.3}
          maxZoom={2}
          // The canvas's own arrow-key instructions ("move the node around")
          // describe behaviour these nodes do not have — selection and keys
          // are owned by ConceptNode — so they are not announced.
          disableKeyboardA11y
        >
          <Background color={token('graph_edge')} gap={24} />
          {/* Spatial context for large graphs: nodes paint in their own
              fills, so the map reads the same as the canvas. The stock
              minimap chrome is unthemed for this pass, like the rest of
              reactflow's stylesheet (see the module docstring). */}
          <MiniMap
            nodeColor={(n) => (n.data as ConceptNodeData).fill ?? token('surface')}
            pannable
            zoomable
          />
        </ReactFlow>
      </Box>

      {/* Click evidence — what hover showed in the Streamlit SVG, split by
          direction: what the concept needs first vs what it unlocks. */}
      {shownSelected != null && (
        <Card>
          <CardContent>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
              {shownSelected}
              {rankOf(shownSelected) != null && (
                <Typography component="span" variant="body2" sx={{ color: 'text.secondary' }}>
                  {' '}
                  · learner step {rankOf(shownSelected)! + 1} of {order.length}
                </Typography>
              )}
            </Typography>
            {incident.length === 0 && (
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                No prerequisite links touch this concept in the current filter.
              </Typography>
            )}
            {needsFirst.length > 0 && (
              <Box sx={{ mt: 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                  NEEDS FIRST ({needsFirst.length}) — study these before {shownSelected}
                </Typography>
                {needsFirst.map((e, i) => (
                  <EdgeRow key={`need-${i}`} edge={e} />
                ))}
              </Box>
            )}
            {unlocks.length > 0 && (
              <Box sx={{ mt: needsFirst.length > 0 ? 2 : 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                  UNLOCKS ({unlocks.length}) — these need {shownSelected}
                </Typography>
                {unlocks.map((e, i) => (
                  <EdgeRow key={`unlock-${i}`} edge={e} />
                ))}
              </Box>
            )}
          </CardContent>
        </Card>
      )}

      {/* Study sequence — the topological order in a bounded scroll box. */}
      {order.length > 0 && (
        <Box>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
            Learner order — the sequence to study in
          </Typography>
          <Box
            sx={{
              maxHeight: 320,
              overflow: 'auto',
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: 2,
              p: 1.5,
            }}
          >
            {order.map((name, i) => (
              <Box
                key={`${i}-${name}`}
                sx={{
                  display: 'flex',
                  gap: 1.5,
                  py: 0.25,
                  borderBottom: '1px solid',
                  borderColor: 'divider',
                  opacity: keptSet.has(name) ? 1 : 0.45,
                }}
              >
                <Typography variant="body2" sx={{ minWidth: 34, fontWeight: 700, color: 'text.secondary' }}>
                  {i + 1}
                </Typography>
                <Typography variant="body2">{name}</Typography>
              </Box>
            ))}
          </Box>
        </Box>
      )}
    </Box>
  )
}

/** Sorted unique values — the methods actually present, for the filter. */
function sortedUnique(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
}
