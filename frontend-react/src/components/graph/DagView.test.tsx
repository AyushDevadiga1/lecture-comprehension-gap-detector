import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DagView } from './DagView'
import type { CourseGraphOut } from '../../api/types'
import { renderWithProviders } from '../../test/render'

/**
 * The view half of the W3.1 port. `graphImportance.test.ts` pins the ranking
 * maths against Python-measured goldens; this pins the wiring the maths feeds:
 * kept nodes draw, the limit cut hides, filters filter, and a click shows the
 * evidence Streamlit used to put on hover.
 *
 * The fixture reuses the golden names so a failure here can be read against
 * the same table: at limit 6 the kept set is known exactly. Note the
 * double space in 'Linear  Regression' is load-bearing — it is the
 * split-on-whitespace-runs trap from the port. Assertion *strings* below use
 * the single-spaced form because Testing Library normalises accessible names
 * (collapse whitespace) before matching but compares a string matcher raw —
 * and the same holds for role+name queries, which cost an hour to learn: a
 * double-spaced regex never matches a normalised name.
 *
 * ## One jsdom compromise, and why it is honest
 *
 * React Flow keeps nodes `visibility: hidden` until the viewport reports
 * dimensions, and jsdom never lays out — so the canvas needs what a browser
 * always provides: a viewport with a size, a transform parser, and non-zero
 * boxes. The three stubs below supply exactly those and nothing more.
 * Without them, every node query needs `hidden: true`, under which the
 * accessible-name computation (which ignores the query option and sees the
 * hidden ancestor) returns "" — role+name queries can then never match, and
 * the failure reads as a component bug. Real visibility is a browser-tier
 * property; the Playwright DAG test asserts it in Chromium.
 *
 * Canvas nodes are clicked with `fireEvent`, not `userEvent`, for a separate
 * jsdom-only reason: `user.click` dispatches a real mousedown first, and
 * d3-zoom's native pan listener (`zoom.js mousedowned` → `nodrag.js`)
 * dereferences a null view in jsdom and throws, breaking the update under
 * test. `fireEvent.click` dispatches only the click, which is exactly the
 * handler under test (React Flow's `onNodeClick` via bubbling). The keyboard
 * path (Enter/Space) takes no part in d3 and *is* exercised with userEvent;
 * both reach the same `select`.
 */

const EDGES = [
  { source: 'Slope', target: 'Linear  Regression', confidence: 0.9, source_method: 'transcript', evidence: 'as we saw, slope drives the fit' },
  { source: 'update', target: 'Slope', confidence: 0.4, source_method: 'classifier', evidence: null },
  { source: 'HAVING', target: 'update', confidence: 0.7, source_method: 'transcript', evidence: null },
]

const NODES = [
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

const ORDER = [
  'update',
  'Slope',
  'Linear  Regression',
  'Conditional Expectation',
  'GROUP BY',
  'INNER JOIN',
  'A1 B2',
  'a',
  'B',
  'filter',
  'xxxxxxxxxxxxxxxxxx',
  'HAVING',
]

const graph: CourseGraphOut = {
  course_id: 'ml',
  nodes: NODES,
  edges: EDGES,
  node_count: NODES.length,
  edge_count: EDGES.length,
  is_dag: true,
  topological_order: ORDER,
}

function renderDag(extra?: Partial<CourseGraphOut>) {
  return renderWithProviders(<DagView graph={{ ...graph, ...extra }} idPrefix="test" />)
}

class MeasuringObserver {
  private readonly callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  observe(target: Element): void {
    this.callback(
      [
        {
          target,
          contentRect: { width: 1280, height: 800 },
        } as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    )
  }
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): ResizeObserverEntry[] {
    return []
  }
}

const savedOffsets: {
  width?: PropertyDescriptor | undefined
  height?: PropertyDescriptor | undefined
} = {}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', MeasuringObserver)
  // React Flow reads the viewport zoom out of the CSS transform
  // (`new window.DOMMatrixReadOnly(style.transform).m22`) while measuring
  // nodes. jsdom implements neither the constructor nor transforms; an empty
  // transform means zoom 1, which is exactly what this returns.
  vi.stubGlobal('DOMMatrixReadOnly', class DOMMatrixReadOnlyStub {
    readonly m22 = 1
    constructor(_init?: string) {
      void _init
    }
  })
  // Nodes initialise only once measured non-zero (`initialized:
  // !!node.width && !!node.height`, read from offsetWidth/offsetHeight, both
  // always 0 in jsdom). A browser always reports real boxes; report fixed
  // ones. Saved and restored per test — a global nonzero box would leak into
  // every other suite's layout assumptions.
  const proto = HTMLElement.prototype as unknown as Record<string, unknown>
  savedOffsets.width = Object.getOwnPropertyDescriptor(proto, 'offsetWidth')
  savedOffsets.height = Object.getOwnPropertyDescriptor(proto, 'offsetHeight')
  Object.defineProperty(proto, 'offsetWidth', { configurable: true, value: 180 })
  Object.defineProperty(proto, 'offsetHeight', { configurable: true, value: 56 })
})

afterEach(() => {
  const proto = HTMLElement.prototype as unknown as Record<string, unknown>
  for (const [key, descriptor] of Object.entries(savedOffsets)) {
    if (descriptor) Object.defineProperty(proto, key, descriptor)
    else delete proto[key]
  }
  savedOffsets.width = undefined
  savedOffsets.height = undefined
})

/**
 * A canvas node, by its accessible name. Async: React Flow initialises nodes
 * after measuring (see the observer stubs above), so the first render has no
 * buttons yet and a synchronous query races initialisation.
 */
async function nodeButton(name: string | RegExp) {
  return screen.findByRole('button', { name })
}

function queryNodeButton(name: string | RegExp) {
  return screen.queryByRole('button', { name })
}

describe('DagView', () => {
  it('draws the kept nodes and the counts line', async () => {
    renderDag()
    // 12 nodes <= READABLE_ALL, so every node draws by default.
    expect(screen.getByText(/12 concepts in total/)).toBeInTheDocument()
    expect(screen.getByText(/12 shown/)).toBeInTheDocument()
    expect(screen.getByText(/acyclic/)).toBeInTheDocument()
    // Nodes are buttons (clickable); the study sequence reuses the names as
    // plain text, so the role is what distinguishes them. Exactly one button
    // per concept — the canvas wrapper must not add its own (it does when a
    // node is left selectable or focusable; see ConceptNode).
    expect(await screen.findAllByRole('button', { name: /Slope/ })).toHaveLength(1)
  })

  it('says cyclic when the payload says so', () => {
    renderDag({ is_dag: false })
    expect(screen.getByText(/contains cycles/)).toBeInTheDocument()
  })

  it('renders an empty graph as guidance, not a blank canvas', () => {
    renderDag({ nodes: [], edges: [], node_count: 0, edge_count: 0, topological_order: [] })
    expect(screen.getByText(/no graph yet/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Course prerequisite graph')).not.toBeInTheDocument()
  })

  it('clicking a node shows its incident edges with method and evidence', async () => {
    renderDag()

    fireEvent.click(await nodeButton(/Slope/))

    expect(screen.getByText('Slope → Linear Regression')).toBeInTheDocument()
    expect(screen.getByText('spoken in lecture')).toBeInTheDocument()
    expect(screen.getByText(/as we saw, slope drives the fit/)).toBeInTheDocument()
    expect(screen.getByText('classifier-inferred')).toBeInTheDocument()
    expect(screen.getByText(/learner step 2 of 12/)).toBeInTheDocument()
  })

  it('clicking the selected node again dismisses the evidence', async () => {
    renderDag()

    const node = await nodeButton(/Slope/)
    fireEvent.click(node)
    expect(screen.getByText('Slope → Linear Regression')).toBeInTheDocument()
    fireEvent.click(node)
    expect(screen.queryByText('Slope → Linear Regression')).not.toBeInTheDocument()
  })

  it('keyboard Enter on a focused node selects it', async () => {
    const user = userEvent.setup()
    renderDag()

    ;(await nodeButton(/Slope/)).focus()
    await user.keyboard('{Enter}')

    expect(screen.getByText('Slope → Linear Regression')).toBeInTheDocument()
  })

  it('unchecking an edge type removes its links from the count', async () => {
    const user = userEvent.setup()
    renderDag()

    expect(screen.getByText(/Links drawn 3 \/ 3/)).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Edge types' }))
    const option = await screen.findByRole('option', { name: /transcript/ })
    await user.click(option)
    // Close the menu so the canvas re-renders without the portal open.
    await user.keyboard('{Escape}')

    await waitFor(() => {
      // Only the classifier edge (update → Slope) still draws.
      expect(screen.getByText(/Links drawn 1 \/ 3/)).toBeInTheDocument()
    })
  })

  it('the confidence slider hides weak links and the counts follow', async () => {
    const user = userEvent.setup()
    renderDag()

    expect(screen.getByText(/Links drawn 3 \/ 3/)).toBeInTheDocument()

    const slider = screen.getByRole('slider', { name: 'Min confidence' })
    slider.focus()
    // 5% a press; at 40% the 0.4 classifier edge is AT the floor and stays —
    // "min" is inclusive, and this boundary is the one a `>` would get wrong.
    for (let i = 0; i < 8; i++) await user.keyboard('{ArrowRight}')
    expect(screen.getByText(/Min confidence 40%/)).toBeInTheDocument()
    expect(screen.getByText(/Links drawn 3 \/ 3/)).toBeInTheDocument()
    expect(screen.queryByText(/lower-confidence link/)).not.toBeInTheDocument()

    // One more press cuts it: count, readout and caption stay in step...
    await user.keyboard('{ArrowRight}')
    await waitFor(() => {
      expect(screen.getByText(/Links drawn 2 \/ 3/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Min confidence 45%/)).toBeInTheDocument()
    expect(
      screen.getByText(/1 lower-confidence link\(s\) hidden below 45%/),
    ).toBeInTheDocument()
    // ...and "hidden" means gone from the canvas, not faded.
    expect(document.querySelectorAll('.react-flow__edge-path')).toHaveLength(2)

    // Back to 0%: the cut reverses and everything returns.
    for (let i = 0; i < 9; i++) await user.keyboard('{ArrowLeft}')
    await waitFor(() => {
      expect(screen.getByText(/Links drawn 3 \/ 3/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/lower-confidence link/)).not.toBeInTheDocument()
  })

  it('the limit slider hides lower-significance concepts and says so', async () => {
    const user = userEvent.setup()
    renderDag()

    const slider = screen.getByRole('slider', { name: 'Concepts shown' })
    slider.focus()
    // 12 → 7 in one step of five; each press is one ranked cut.
    await user.keyboard('{ArrowLeft}')

    await waitFor(() => {
      expect(screen.getByText(/7 shown/)).toBeInTheDocument()
    })
    expect(screen.getByText(/5 lower-significance concept\(s\) hidden/)).toBeInTheDocument()
    // 'B' scores -3.5, the lowest in the fixture — first to go.
    expect(queryNodeButton(/^B, learner step/)).not.toBeInTheDocument()
    expect(await nodeButton(/Linear Regression/)).toBeInTheDocument()
  })

  it('the study sequence lists the topological order, dimming hidden nodes', async () => {
    const user = userEvent.setup()
    renderDag()

    expect(screen.getByText(/Learner order — the sequence/)).toBeInTheDocument()

    const slider = screen.getByRole('slider', { name: 'Concepts shown' })
    slider.focus()
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => {
      expect(screen.getByText(/7 shown/)).toBeInTheDocument()
    })
    // The sequence still lists every step — hiding is a canvas cut, not a
    // curriculum cut — with the full order intact.
    const items = screen.getAllByText('update')
    expect(items.length).toBeGreaterThanOrEqual(2)
  })

  it('switching colour-by to identity keeps every node drawn', async () => {
    const user = userEvent.setup()
    renderDag()

    await user.click(screen.getByRole('combobox', { name: 'Colour by' }))
    const option = await screen.findByRole('option', { name: /Concept identity/ })
    await user.click(option)

    // Same twelve nodes, different ramp — nothing lost in the switch.
    await waitFor(() => {
      expect(screen.getByText(/12 shown/)).toBeInTheDocument()
    })
    expect(await nodeButton(/Slope/)).toBeInTheDocument()
  })

  it('renders a minimap and a reset-view affordance', async () => {
    const user = userEvent.setup()
    renderDag()

    // The map paints nodes in their own fills — spatial context that reads
    // the same as the canvas.
    await screen.findByRole('button', { name: /Slope/ })
    expect(document.querySelector('.react-flow__minimap')).not.toBeNull()

    // Reset is a visible button, not an inferred gesture: clicking it must
    // neither throw nor disturb the drawing.
    await user.click(screen.getByRole('button', { name: 'Reset view' }))
    expect(await nodeButton(/Slope/)).toBeInTheDocument()
    expect(screen.getByText(/12 shown/)).toBeInTheDocument()
  })

  it('draws arrowheads so link direction reads', async () => {
    renderDag()
    await screen.findByRole('button', { name: /Slope/ })

    // React Flow renders one <marker> def per distinct arrowhead; without
    // markerEnd the canvas is directionless lines and prerequisites read
    // either way.
    expect(document.querySelector('marker')).not.toBeNull()
  })

  it('selecting a concept dims everything unrelated and lights its links', async () => {
    renderDag()
    fireEvent.click(await nodeButton(/Slope/))

    const opacityOf = (id: string) =>
      document.querySelector(`[data-id="${id}"]`)?.getAttribute('style') ?? ''
    // Slope plus its two neighbours stay; 'B' (unrelated, lowest score) recedes.
    expect(opacityOf('Slope')).toContain('opacity: 1')
    expect(opacityOf('update')).toContain('opacity: 1')
    expect(opacityOf('B')).toContain('opacity: 0.35')

    // Both incident edges carry the accent stroke now.
    const hot = [...document.querySelectorAll('.react-flow__edge-path')].filter((p) =>
      (p.getAttribute('style') ?? '').includes('lgc-accent'),
    )
    expect(hot).toHaveLength(2)
  })

  it('find-concept selects the first match and says how many there were', async () => {
    const user = userEvent.setup()
    renderDag()

    await user.click(screen.getByRole('textbox', { name: 'Find concept' }))
    await user.keyboard('slo')
    await user.keyboard('{Enter}')

    // Selected (evidence panel) and announced (single match → no note needed).
    expect(await screen.findByText('Slope → Linear Regression')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('find-concept reports multiple matches and hidden matches honestly', async () => {
    const user = userEvent.setup()
    renderDag()

    // 'a' matches several shown concepts — first wins, count stated.
    await user.click(screen.getByRole('textbox', { name: 'Find concept' }))
    await user.keyboard('a')
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('status')).toHaveTextContent(/matches — showing/)

    // Cut to 7, hiding HAVING; searching for it must point at the slider,
    // not pretend nothing matches.
    const slider = screen.getByRole('slider', { name: 'Concepts shown' })
    slider.focus()
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => {
      expect(screen.getByText(/7 shown/)).toBeInTheDocument()
    })
    const box = screen.getByRole('textbox', { name: 'Find concept' })
    await user.clear(box)
    await user.type(box, 'hav')
    await user.keyboard('{Enter}')
    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent(/hidden concept.*raise Concepts shown/)
    })
  })

  it('explains its own encoding in a legend', () => {
    renderDag()
    expect(screen.getByText(/Badge = learner step/)).toBeInTheDocument()
  })

  it('splits evidence into needs-first vs unlocks', async () => {
    renderDag()
    fireEvent.click(await nodeButton(/Slope/))

    // update → Slope must come first; Slope → Linear unlocks after.
    const needsHead = screen.getByText(/NEEDS FIRST \(1\)/)
    const unlocksHead = screen.getByText(/UNLOCKS \(1\)/)
    expect(within(needsHead.parentElement!).getByText('update → Slope')).toBeInTheDocument()
    expect(
      within(unlocksHead.parentElement!).getByText('Slope → Linear Regression'),
    ).toBeInTheDocument()
  })

  it('keeps learner-step badges stable when the limit cut moves', async () => {
    const user = userEvent.setup()
    renderDag()

    // Slope is learner step 2 of 12 with the full graph drawn...
    expect(await nodeButton(/Slope/)).toHaveAttribute(
      'aria-label',
      'Slope, learner step 2',
    )

    // ...and still step 2 of 12 after the cut to 7. Badges name positions in
    // the topological order, not positions among the drawn — renumbering on
    // every filter move would make steps meaningless across views.
    const slider = screen.getByRole('slider', { name: 'Concepts shown' })
    slider.focus()
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => {
      expect(screen.getByText(/7 shown/)).toBeInTheDocument()
    })
    expect(await nodeButton(/Slope/)).toHaveAttribute(
      'aria-label',
      'Slope, learner step 2',
    )
  })

  it('drops the evidence panel when its node is filtered out, restores on return', async () => {
    const user = userEvent.setup()
    renderDag()

    // 'filter' draws at 12 but not at 7. Selecting it, then cutting, must
    // not leave an evidence card for a ghost — and raising the limit back
    // must restore it without re-clicking, because the selection itself was
    // never destroyed, only hidden.
    fireEvent.click(await nodeButton(/^filter, learner step/))
    expect(screen.getByText(/learner step 10 of 12/)).toBeInTheDocument()

    const slider = screen.getByRole('slider', { name: 'Concepts shown' })
    slider.focus()
    await user.keyboard('{ArrowLeft}')
    await waitFor(() => {
      expect(screen.getByText(/7 shown/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/learner step 10 of 12/)).not.toBeInTheDocument()

    await user.keyboard('{ArrowRight}')
    await waitFor(() => {
      expect(screen.getByText(/12 shown/)).toBeInTheDocument()
    })
    expect(await screen.findByText(/learner step 10 of 12/)).toBeInTheDocument()
  })

  it('ellipsises long names instead of breaking the row pitch', async () => {
    const longName = 'A concept name far too long for any node box to hold intact'
    renderDag({
      nodes: [longName],
      edges: [],
      node_count: 1,
      edge_count: 0,
      topological_order: [longName],
    })

    // Full name survives in title and aria-label; the visible label truncates
    // so the fixed row pitch holds no matter what the backend names things.
    // (title lives on the label inside the node root, not on the root.)
    const node = await screen.findByRole('button', { name: new RegExp(longName) })
    const label = within(node).getByText(longName)
    expect(label).toHaveAttribute('title', longName)
  })
})
