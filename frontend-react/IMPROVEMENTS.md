# Frontend Improvement Plan

> LecGap React frontend (`frontend-react/`) — living plan for improvements
> that are worth making to the current codebase. Not a roadmap promise; a
> working notes file for the next pass.

The app is running and the two components most recently touched (DagView,
QuizPanel) are in good shape. The items below are the improvements I'd rank
highest after reading `client.ts`, `StudentDashboard.tsx`, `DagView.tsx` and
`QuizPanel.tsx` against the running app.

---

## 1. Upload progress bar rarely moves (bug, high impact)

**File:** `src/api/client.ts` — `putStream()`

**Problem:** The XHR `upload.onprogress` handler only reports progress when
`e.lengthComputable` is true, but for `File` bodies most browsers report
`lengthComputable: false`. The bar stays at 0% for the whole upload and the
user gets no real feedback. The existing comment already explains exactly why
this happens and names the right fallback — the code just doesn't use it.

**Current code (paraphrased):**

```typescript
xhr.upload.onprogress = (e) => {
  if (e.lengthComputable && e.total > 0) {
    onProgress(Math.round((e.loaded / e.total) * 100))
  }
}
```

**Fix:**

- When `lengthComputable` is true, keep the existing `loaded / total` path.
- When it is false, fall back to `body.size` (the File always exposes its
  size) and report `Math.round((e.loaded / body.size) * 100)` as a
  best-effort percentage.
- Keep the bar honest: if we can't compute any percentage at all, show an
  indeterminate state rather than a frozen 0%.

**Why this is the right fix:** The comment in the same function already says
exactly this — that `lengthComputable` is frequently false for File bodies and
that the honest move is to report loaded bytes rather than freeze the bar. The
only gap is that the code and the comment disagree.

---

## 2. React Flow edge stroke uses a token that can silently render invisible

**File:** `src/components/graph/DagView.tsx` — `flowEdges`

**Problem:** Every edge is styled with `stroke: token('graph_edge')`. If the
`graph_edge` token is missing, misspelled, or resolves to a color too close to
the canvas background, the edges disappear against the nodes. That is a silent,
visual-only failure — no console error, no test that asserts edges are visible
in the browser tier, just an empty-looking graph.

This risk applies to other tokens used in `sx` props across the app too
(`tint('text', 8)`, `token('track')`, `token('accent')`, etc.).

**Fix (pick one or both):**

- Add a defensive fallback on the edge style so an undefined/empty token can't
  render edges as `none` or `transparent`. For example, resolve the token and
  fall back to a known-safe value if it is empty.
- Add a small guard in `token()` (or a build-time token table check) so that a
  misspelled token name is caught early rather than producing an invalid CSS
  value that fails silently at computed-value time.

**Why this matters:** The same class of bug already bit this codebase once —
the prior fix to `src/theme/alpha.ts` exists because `token('graph_edge')`
used to emit `var(--lgc-graph_edge)`, a custom property that was never defined,
which made the prerequisite links vanish while the nodes stayed visible. The
current token helper is better, but any token is still only as good as the
property it reads.

---

## 3. DAG has no minimap, no explicit reset-zoom affordance

**File:** `src/components/graph/DagView.tsx` — `<ReactFlow>` canvas

**Problem:** The canvas turns on `fitView` and exposes pan/zoom, but:

- There is no minimap, so for a 150-node graph the user has no spatial context
  once they pan away from the initial fit.
- There is no explicit "reset to fit" affordance. If a user zooms/pans to a
  weird spot, the only ways back are refresh or discovering scroll-to-zoom by
  accident.
- The hint text says "scroll to zoom" but that affordance is easy to miss.

**Fix:**

- Add `<Minimap nodeColor={(n) => (n.data as ConceptNodeData).fill} />` from
  reactflow. It is built in and gives spatial context for large graphs.
- Add a small "Reset zoom" control, or re-fit on a recognisable gesture (e.g.
  double-click on an empty area), so users aren't trapped at an arbitrary zoom.
- Keep the "scroll to zoom" hint, but make the reset affordance visible enough
  that users don't have to infer pan/zoom from the hint text alone.

**Note:** Keep this light. The DAG is intentionally austere (no zoom slider, no
Controls chrome). A minimap + one reset affordance is the right magnitude —
not a full reactflow toolbar.

---

## 4. Quiz scroll UX on mobile could be clearer

**File:** `src/features/student/QuizPanel.tsx`

**Problem:** The three scroll regions (`maxHeight: '54vh'`, `320px`,
`420px`) all already exist and correctly use `overscrollBehavior: 'contain'`.
The containers are real; the gaps are in fit and affordance:

- On a short mobile viewport, `54vh` can still leave the question region too
  short to read a full question + options comfortably, with the submit bar
  sitting close to the last option.
- There is no visual cue that a region is scrollable (no fade edge, no scroll
  indicator), so a user who doesn't scroll explicitly may not realize there is
  more content inside the card.

**Fix:**

- On small viewports, prefer a height that uses available space rather than a
  fraction of viewport height that may be too small — something like
  `calc(100vh - <header + card chrome>)`.
- Add a subtle gradient fade or scroll cue at the top/bottom of a scroll
  region when its content overflows, so it is obvious the region scrolls.
- Make sure the submit bar has enough breathing room that the last option isn't
  visually cramped against it.

**Do not:** remove `overscrollBehavior: 'contain'` — that is the correct choice
and pins the progress/submit chrome outside the scroll region.

---

## 5. StudentDashboard upload card and lecture table could be more polished across widths

**File:** `src/features/student/StudentDashboard.tsx`

**Problem:** The page works, but two areas are not maximally polished:

- The upload card stacks every control vertically (title field, dashed file
  picker, progress bar, submit button) even on wide screens where there is room
  to put the title field and file picker side by side.
- The lecture table has 6 columns; on narrow viewports the "Pipeline Actions"
  column with three buttons can wrap awkwardly.

**Fix:**

- On large screens, let the title field and file picker share a row so the
  upload card is shorter.
- Make the actions column more robust on narrow widths — icon buttons with
  tooltip labels, or a compact kebab / expandable action row, so it does not
  need as much horizontal room.

**Priority:** Medium-low. The current layout is honest and usable; these are
polish items for the common case, not bug fixes.

---

## 6. DAG loading fallback is a full-screen loading screen, not a scoped skeleton

**File:** `src/features/student/StudentDashboard.tsx` — `<Suspense>` around
`<DagView>`

**Problem:** The DAG is lazy-loaded, and the Suspense fallback is a full
`LoadingScreen`. That is honest, but:

- On a slow connection it covers the entire lower half of the page even though
  the lecture table above it is already interactive.
- On a cached revisit, the switch from "loading" to "graph" can still feel
  abrupt.

**Fix:**

- Use a skeleton that matches the graph card's shape (a bordered box with a
  shimmer) as the fallback, instead of the full-screen loading screen.
- Or at least scope the fallback to the graph card only, so the rest of the
  page remains visually present while the chunk loads.

**Priority:** Low. Cosmetic, but easy to make the page feel more intact during
chunk load.

---

## Priority summary

| # | Improvement | Priority | Kind | Effort |
|---|---|---|---|---|
| 1 | Upload progress actually fills | **High** | Bug fix | Small |
| 2 | Edge stroke token fallback / token validation | **High** | Safety + bug prevention | Small |
| 3 | DAG minimap + reset zoom | Medium | UX | Small-medium |
| 4 | Quiz scroll UX on mobile | Medium | UX polish | Small |
| 5 | Dashboard upload card + table layout polish | Low-medium | Polish | Medium |
| 6 | DAG skeleton fallback instead of full loading screen | Low | Polish | Small |

---

## Before starting any improvement

- The app must be running: backend on `:8000`, frontend on `:5173` with the
  fixed `vite.config.ts` proxy.
- Re-read the file you are about to edit — this plan is notes, not a spec, and
  the code may have moved.
- Prefer small, reviewable edits over bundled refactors.
- If an improvement would change behaviour that the existing testsAssert on,
  update the test with the change, not around it.
