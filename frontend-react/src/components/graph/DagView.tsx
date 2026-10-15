import React from 'react'
import ReactFlow, { Background, Handle, Position } from 'reactflow'
import type { Edge as FlowEdge, Node as FlowNode, NodeProps } from 'reactflow'
import 'reactflow/dist/style.css'
import {
  Alert,
  Box,
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
  Typography,
} from '@mui/material'
import type { SelectChangeEvent } from '@mui/material/Select'
import type { CourseGraphOut, GraphEdgeOut } from '../../api/types'
import { rankConcepts } from '../../lib/graphImportance'
import { nodeColors } from '../../theme/nodeColors'
import { token } from '../../theme/alpha'

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
 *   - the learner-order study sequence in a bounded scroll box.
 *
 * What is new, because an SVG layout does not transfer to a canvas:
 *   - positions come from a deterministic layered layout (depth = longest
 *     prerequisite chain, guarded against cycles; order within a layer follows
 *     the topological order), not from `dag_svg`;
 *   - hover evidence becomes **click evidence**: selecting a node lists its
 *     incident edges with confidence, method and recorded evidence;
 *   - pan/zoom are the canvas's own (drag to pan, scroll to zoom, fit on load),
 *     so there is no zoom slider and no `<Controls>` chrome to theme.
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
        borderRadius: 2,
        px: 1.5,
        py: 1,
        minWidth: 150,
        maxWidth: 190,
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        border: '1px solid',
        borderColor: 'divider',
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
            fontWeight: 800,
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
      <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.25 }}>
        {data.label}
      </Typography>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </Box>
  )
}

// Module scope (not exported): reactflow warns on an inline `nodeTypes` object
// because a fresh identity remounts every node on each render.
const nodeTypes = { concept: ConceptNode }

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

  const methodsPresent = React.useMemo(() => {
    const found = sortedUnique(edges.map((e) => e.source_method || 'classifier'))
    return found.length ? found : ['classifier']
  }, [edges])
  const wanted = methods ?? methodsPresent

  const [limit, setLimit] = React.useState<number>(() =>
    nodes.length <= READABLE_ALL ? nodes.length : DEFAULT_LIMIT,
  )

  const { kept, dropped } = React.useMemo(
    () => rankConcepts(nodes, edges, limit),
    [nodes, edges, limit],
  )

  const rankOf = React.useMemo(() => {
    const index = new Map(order.map((name, i) => [name, i] as const))
    return (name: string): number | null => index.get(name) ?? null
  }, [order])

  const keptSet = React.useMemo(() => new Set(kept), [kept])
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
          data: {
            label: name,
            fill,
            ink,
            rankLabel: rank == null ? null : String(rank + 1),
            pressed: selected === name,
            select: () => setSelected((cur) => (cur === name ? null : name)),
          },
        }
      }),
    [kept, rankOf, order.length, colorBy, positions, selected],
  )

  const flowEdges: FlowEdge[] = React.useMemo(
    () =>
      shownEdges.map((e, i) => ({
        id: `${e.source}→${e.target}#${i}`,
        source: e.source,
        target: e.target,
        // Decorative paths: no click behaviour reads them, so they must not
        // be buttons. (Focusable edges get role=button plus an auto label.)
        focusable: false,
        style: { stroke: token('graph_edge'), strokeWidth: 1.5 },
      })),
    [shownEdges],
  )

  const drawnCount = React.useMemo(() => {
    const wantedSet = new Set(wanted)
    return edges.filter(
      (e) =>
        keptSet.has(e.source) &&
        keptSet.has(e.target) &&
        wantedSet.has(e.source_method || 'classifier'),
    ).length
  }, [edges, keptSet, wanted])

  const incident = React.useMemo(() => {
    if (selected == null) return []
    return edges.filter((e) => e.source === selected || e.target === selected)
  }, [edges, selected])

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
      {/* Controls — the same four as panels/graph.py::_controls. */}
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
      </Box>

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

      {/* Canvas. Pan by dragging, zoom by scrolling; fits on load. */}
      <Box
        aria-label="Course prerequisite graph"
        sx={{
          height: 480,
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
        </ReactFlow>
      </Box>

      {/* Click evidence — what hover showed in the Streamlit SVG. */}
      {selected != null && (
        <Card>
          <CardContent>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
              {selected}
              {rankOf(selected) != null && (
                <Typography component="span" variant="body2" sx={{ color: 'text.secondary' }}>
                  {' '}
                  · learner step {rankOf(selected)! + 1} of {order.length}
                </Typography>
              )}
            </Typography>
            {incident.length === 0 && (
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                No prerequisite links touch this concept in the current filter.
              </Typography>
            )}
            {incident.map((e, i) => (
              <Box key={i} sx={{ py: 1, borderTop: i ? '1px solid' : 'none', borderColor: 'divider' }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {e.source} → {e.target}
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 0.5, flexWrap: 'wrap' }}>
                  <Chip
                    size="small"
                    label={
                      e.source_method === 'transcript'
                        ? 'spoken in lecture'
                        : 'classifier-inferred'
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
            ))}
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
