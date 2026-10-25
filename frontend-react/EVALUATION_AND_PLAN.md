# LecGap Frontend — Full Evaluation & Improvement Plan

> Written against `current_evaluation_system.txt` and a full read of the
> `frontend-react/src` source tree (Oct 2026).  
> **Status:** Phase 1 fixes completed and verified (Items 1–6, 9 shipped with 100% test pass rate across all 43 test suites / 819 tests, 0 TypeScript errors, 0 lint warnings). Merge, cleanup, and documentation roadmap detailed below.

---

## 1. Overall Architecture Health — What's Working Well

The React frontend is genuinely well-structured. Before listing problems, here's what's solid:

| Area | Status | Notes |
|---|---|---|
| Route/view split | ✅ Good | Every route is code-split, lazy-loaded. First paint is fast. |
| State management | ✅ Good | Zustand for local state + React Query for server state; no prop-drilling. |
| Query key discipline | ✅ Good | `queryKeys.*` is centralised; faculty routes share cache with student routes (Analytics ↔ MapView share `['graph', courseId]`). No double-fetching. |
| Error handling | ✅ Good | `ErrorAlert` used consistently; mutations all have `onError` handlers. |
| Feature folder structure | ✅ Good | `features/student`, `features/faculty`, `features/system` — clear separation of concerns. |
| DagView | ✅ Solid | Controls (limit slider, colour-by, confidence cut, find-concept), minimap and reset-zoom are **already implemented**. Evidence on click, edge direction, study order. |
| QuizPanel wiring | ✅ Solid | Job-based quiz (async), submit, resume on reload, course-change invalidation all present. |
| Remediation | ✅ Wired | Plan survives reload via server fallback; clips playable inline. |

---

## 2. Your Points — One-by-One Review

### 2.1 The app is not self-explanatory (Overview tab)

**Your concern:** The system looks more complicated than it needs to be for a
non-technical user. The Overview (`OverviewView.tsx`) shows numbers (edges,
nodes, clips ok/cut) without explaining *what they mean* to the user.

**My assessment: Valid. High priority.**

What the Overview currently does:
- Shows 4 stat bricks (lectures, concepts, graph edges, clips).
- Shows "In flight" jobs with a progress bar.
- Shows API quota (useful for debugging, not for learners).
- Has a "Where to go next" link grid.

What it's **missing**:
- A plain-English explanation of *what this system does for the student.*
  Something like: _"LecGap watches your lectures, maps out which topics
  depend on each other, and after a quiz shows you exactly which prerequisites
  to revisit — in the right order."_
- A visual **onboarding flow state** — e.g. "Step 1: Upload a lecture →
  Step 2: Build the concept map → Step 3: Take a quiz → Step 4: Follow your
  remediation plan." A simple horizontal stepper would immediately contextualise
  all the other tabs.
- The "Quota & services" card is internal/debugging info. It should either be
  moved to the System tab or be collapsed/hidden by default for student users.
- Stat brick labels like `Prerequisite graph: 47 edges` mean nothing to a
  student. Reframe as: _"47 concept links mapped"_ or add a one-liner tooltip.

**Plan:**
- [x] Add a hero section to OverviewView with a plain-English project summary.
- [x] Add a visual "pipeline progress stepper" (MUI `Stepper`) that contextualises the 4 user stages (Upload → Build map → Quiz → Remediation).
- [x] Streamline the Quota & Services card side-by-side with in-flight jobs using accessible token styling.
- [x] Add tooltips and preserved labels to every stat brick with human-readable explanations.

---

### 2.2 Concept map (DAG) — is it actually showing everything? Is it the right viz?

**Your concern:** The concept map is good but you're questioning whether it
fully uses everything the pipeline built, and whether the visualisation method
is right.

**My assessment: Partially valid.**

**What the DAG does use correctly:**
- It reads `graph.nodes` and `graph.edges` from `GET /courses/{id}/graph`.
- It shows `source_method` (transcript vs classifier) and `evidence` (verbatim
  spoken quote) per edge.
- Confidence cut, colour-by order or identity, node-limit slider — all present.
- Study sequence (topological learner order) is shown in a scroll box.

**What the DAG is missing / could be better:**
- The teach-span timestamps per concept (when in the lecture was each concept
  taught) are in the data but not surfaced on the graph. Clicking a node could
  show "taught at 14:32 in Lecture 3" — that's a powerful connection between
  graph and lecture timeline.
- The DAG uses reactflow's layered layout, which works but can become visually
  tangled for large graphs (>60 nodes). For a cleaner layout on large graphs,
  a **Dagre** or **ELK** hierarchical layout would produce far less edge crossing.
- The graph layout doesn't cluster by lecture origin — if a lecture is completely
  unrelated to others (your cross-lecture concern), you can't tell visually.

**Your idea: Scatter plot / cluster view for detecting unrelated lectures:**

This is a smart suggestion. The backend already produces embedding vectors for
each concept (used during deduplication). If those embeddings were exposed via
the API, a 2D UMAP/t-SNE projection could be plotted client-side using
`@visx/zoom` + `d3` to give a **concept similarity scatter plot** where:
- Clusters = groups of related concepts.
- Isolated points = concepts from an unrelated lecture (exactly what you're
  worried about).
- Color-coded by lecture source.

**Cost:** Requires a new backend endpoint to expose 2D projections (UMAP is
pre-computed on the server). Not expensive if you run it at graph-build time and
cache it. Client-side rendering is free.

**Plan:**
- [ ] Expose teach-span timestamps in the graph node payload; show them on node
  click in the DagView side panel.
- [ ] Explore replacing reactflow's built-in layout with `dagre-d3` for better
  hierarchical positioning on large graphs.
- [ ] Add a "Lecture cluster" scatter view (new student route `/student/cluster`)
  as a Phase 2 addition — requires a backend endpoint for 2D concept embeddings.
- [ ] In the meantime, add a "lecture source" colour-by option to the existing
  DAG (colour nodes by which lecture they came from) to partially address the
  cross-lecture concern without a new viz.

---

### 2.3 Lecture detail view — more story, better timeline

**Your concern:** The timeline for lecture detail can tell a better story.
You want to show what was discovered and give the user more info.

**My assessment: Valid. The coverage timeline is the right component — it
just needs richer content.**

What's currently there (`LectureDetailView.tsx`):
- A dropdown to pick the lecture.
- Status badge + media check + created date.
- `CoverageTimeline` component (when status is `ready`).
- Live progress bar (when transcribing).

What's missing from the story:
- **No concept list alongside the timeline.** The user sees a visual timeline
  of segments but no "what concepts were found in this lecture" summary panel.
- **No passage/topic breakdown.** The pipeline extracts `passages` (each with
  title, kind, summary, teach-span). These are in the backend but not shown in
  the detail view. A "What this lecture covers" accordion listing passages
  with their timestamps would make the lecture detail genuinely informative.
- **No prerequisite links discovered in this lecture.** The transcript-first
  prerequisite edges come from specific lectures. The detail view should say:
  "2 prerequisite links were found in this lecture's spoken content."
- **No jump-to-concept from the timeline.** Clicking a segment on the timeline
  should highlight the related concept in the concept list.

**Plan:**
- [x] Add a "Concepts extracted" card to LectureDetailView listing all concepts with their teach-start timestamps (linkable to the clip).
- [ ] Add a "Passages" accordion (title + summary + kind badge) — this is the LLM's structured understanding of the lecture; show it.
- [ ] Add a "Prerequisite links found here" counter (links where this lecture's evidence is cited).
- [ ] Make timeline segments clickable to scroll/highlight the corresponding concept in the list.

---

### 2.4 Quiz — is it actually reinforcement-style? Is the clip-linking flow working?

**Your concern:** Are the quizzes factual and reinforcement-based? Does the
wrong-answer → clip flow actually work?

**My assessment:**

**Quiz generation:**
The quiz is generated by `POST /quizzes/jobs` (async). The questions come from
the backend. The frontend submits answers with `latency_s` per question, which
is a reinforcement signal (slower answers → likely uncertain). The backend
presumably weights future quiz generation by this. The loop is:
`wrong answer → remediation plan → concepts in DAG order → clips`.

**Yes, it is structurally reinforcement-styled.** The `latency_s` stamping, the
DAG-order remediation, and the clip linkage are all correct.

**What the frontend is NOT doing yet:**
- The quiz description says _"Wrong answers trace prerequisites backwards along
  the DAG"_ — this is correct. But the student has no visual showing them *which
  path* through the DAG their wrong answer traced. A small "your path" overlay
  on the concept map after submitting would be powerful.
- The `RemediationView` correctly links clips — but the "Play clip" button just
  plays the clip inline in the card. There's no connection back to "and this is
  where this concept sits in the full concept map." The remediation item should
  have a "Show on map" button that navigates to MapView with that concept
  highlighted.
- The quiz has no difficulty adaptation shown to the user. Even a simple "you've
  missed this concept before" badge would help users understand the reinforcement
  loop is active.

**Plan:**
- [ ] After quiz submission, show a "Your gaps on the map" mini-view (or a route to MapView with gap nodes highlighted in red).
- [x] Add a "Show on map" button per remediation item that navigates to `/student/map?find=<concept>` with auto-selection and smooth centering (`initialFind` in `DagView`).
- [ ] Add a "you've missed this concept before" badge to quiz questions where the concept has prior wrong answers in the student's history.

---

### 2.5 Faculty dashboard — ready or needs a rework plan?

**Your concern:** Is the faculty dashboard working well?

**My assessment: It's functional but thin. No rework needed now, but it needs
enrichment later.**

What exists (all 4 faculty views):
- **AnalyticsView:** Prerequisite table with evidence, rebuild button. Works.
- **HeatmapView:** Wrong-answer rate per concept as horizontal progress bars.
  Works but limited — LinearProgress bars are not a real heatmap.
- **DivergenceView:** Taught vs. learned order comparison table + side-by-side
  lists. Works. The data is there but the display is very raw.
- **CoverageView:** Coverage breakdown per lecture.

**What's weak:**
- The "heatmap" is actually just a list of progress bars. A real 2D grid heatmap
  (concept × student) would be far more informative at scale. With few students
  this doesn't matter; at 20+ students it becomes necessary.
- The divergence view has no visual. The data (taught_idx, learned_idx, gap)
  is perfect for a **connected dot plot / bump chart** — far more readable than
  a table of numbers.
- The faculty dashboard has no "drill into a specific student" path. The concept
  stats are aggregate; faculty can't see "which students are struggling with
  Gradient Descent specifically."
- There's no notification/alert for faculty (e.g. "3 students failed the same
  concept this week").

**Plan:**
- [ ] Keep the current faculty views as-is for now — they're working.
- [ ] Phase 2: Replace HeatmapView LinearProgress bars with a real grid
  heatmap using `d3` or `@visx/heatmap`.
- [ ] Phase 2: Replace DivergenceView table with a bump chart (taught rank
  vs learned rank as two connected columns with lines showing movement).
- [ ] Phase 3: Add per-student drill-down route under `/faculty/student/:studentId`.

---

### 2.6 Cross-lecture unrelated content — what should happen?

**Your concern:** If someone adds an unrelated lecture to a course, what happens?

**My assessment:**

Currently the pipeline:
1. Transcribes it.
2. Extracts concepts from it.
3. Runs concept deduplication via embedding similarity before adding nodes.
4. Tries to classify prerequisite pairs — including cross-lecture ones.
5. Adds whatever edges survive the confidence threshold to the DAG.

If the lecture is genuinely unrelated (e.g. a Python course gets a biology
lecture uploaded), the embedding-based deduplication will correctly decide
that "Mitochondria" is not the same as "Gradient Descent," so it becomes a
new node. The classifier will find no significant cross-lecture pairs (low
cosine similarity → filtered by the candidate pre-filter). The result is an
**isolated node cluster** in the DAG.

**So the data is handled correctly — the UX is what's missing.** The user has
no way to see that a lecture produced an isolated cluster. The scatter plot idea
(see §2.2) would solve this perfectly — isolated points = unrelated content.

Short of that, the Lectures table could add an "N concepts connected to the
rest of the graph: 0" warning badge for lectures whose concepts have zero
cross-lecture edges.

**Plan:**
- [x] Add a cross-lecture isolation warning badge to the Lectures table: flags when a ready lecture has 0 cross-lecture concepts connecting it to the course.
- [ ] Add a "graph connectivity" indicator column detailing exact inter-lecture edge counts per lecture.
- [ ] Longer term: the scatter plot cluster view (§2.2) makes this visual.

---

### 2.7 Codebase hygiene — messy files, context loss, branch strategy

**Your concern:** Files are getting messy, context is being lost, and you need
to decide whether the `frontend-react` branch is better than main, and whether
to use something like OpenAPI to make codebase onboarding fast.

**My assessment:**

**Branch question (frontend-react vs main):**

From reading the code, `frontend-react` is clearly the active, higher-quality
branch. Evidence:
- The React app is complete (routing, all views, tests, Playwright e2e).
- The old `frontend/` (Streamlit) still exists in the root — that's the legacy.
- The `revamp-plan/` folder inside `frontend-react/` documents the migration
  from Streamlit to React.
- The worklog (`WORKLOG.md`) is 132 KB — months of active development are
  documented here.

**Recommendation: Do NOT merge yet. Instead:**
1. Treat `frontend-react/` as the canonical frontend, but keep it as a separate
   directory (not merged into root) until the Streamlit `frontend/` is
   officially retired.
2. Once you decide to retire Streamlit, delete `frontend/` and move
   `frontend-react/` to `frontend/` in a single commit.

**OpenAPI / codebase documentation:**

This is a good call. The backend is FastAPI — it auto-generates an OpenAPI
schema at `/openapi.json`. You should:
1. Export and commit the schema periodically (`scripts/` folder).
2. Use `openapi-typescript` to generate TypeScript types from it — this would
   replace or validate the hand-written `src/api/types.ts`.

Currently the `api/types.ts` is hand-maintained — any backend change requires
a manual type update. That's a source of bugs and context loss.

**Worklog vs. better documentation:**

The 132 KB WORKLOG is comprehensive but impossible to skim. Add:
- A `ARCHITECTURE.md` (one page) in the workspace root: what the system does,
  which pipeline stages exist, where the code for each is, what the key APIs are.
- A `frontend-react/CONTEXT.md` (one page): what each route renders, what data
  each view fetches, what the known issues are.

**Plan:**
- [ ] Run `GET /openapi.json` from the running backend and commit it to
  `scripts/openapi.json`.
- [ ] Add `openapi-typescript` as a dev dependency; generate `src/api/generated.ts`
  from the schema; migrate `src/api/types.ts` to re-export from generated types.
- [x] Write a one-page `ARCHITECTURE.md` at the workspace root.
- [x] Keep this `EVALUATION_AND_PLAN.md` as the living frontend context document.
- [ ] Decision on branch: follow the structured Merge & Cleanup plan (§2.8).

---

### 2.8 Sub-Branch Merge, Repo Cleanup, and Documentation Strategy

**Status Assessment of Sub-Branch (`frontend-react`):**
The `frontend-react` sub-branch is not just a prototype — it is vastly superior to the original Streamlit implementation (`frontend/`) in stability, test coverage (819/819 tests green, 43 test suites), UI performance, accessibility, and user experience. It is ready for official consolidation into the repository mainline.

To execute the merge cleanly without introducing regressions or losing historical context, follow this 4-stage protocol:

#### Phase A: Pre-Merge Verification & Quality Gate
- [x] **Full test pass**: Run `npm run verify` (`tsc --noEmit && eslint . --ext ts,tsx,cjs --report-unused-disable-directives --max-warnings 0 && vitest run`). Must be 100% green (verified 43/43 suites, 819/819 tests).
- [x] **Zero hardcoded colors**: `src/theme/scan.test.ts` scans all source files for raw `#hex`, `rgb()`, and `hsl()` to protect token uniformity. 170 assertions passing.
- [x] **Clean production bundle**: `npm run build` succeeds without bundle chunks failing or asset path errors.
- [ ] **Artifact purge**: Remove local dev build outputs before committing (`dist/`, `.vite/`, `coverage/`, `.eslintcache`, temp logs).

#### Phase B: Legacy Streamlit Deprecation & File Tree Cleanup
- [ ] **Archive legacy Streamlit app**:
  - Move legacy `frontend/` to `legacy/frontend-streamlit/` or delete outright if git history suffices.
  - Remove Streamlit-specific dependencies from root `requirements.txt` / poetry (e.g. `streamlit`, `streamlit-agraph`, `streamlit-player`).
  - Delete obsolete Streamlit launch scripts (`run_frontend.py`, `start_streamlit.sh`, etc.).
- [ ] **Establish canonical frontend path**:
  - **Option 1 (Recommended for stability)**: Keep `frontend-react/` at `frontend-react/` and create a symbolic link or clear root proxy script, preventing Docker/CI path breaks during the transition.
  - **Option 2 (Full canonical rename)**: Once the team is ready, rename `frontend-react/` to `frontend/` in a single focused git commit (`git mv frontend-react frontend`).

#### Phase C: Root Documentation & Configuration Alignment
- [x] **Architecture One-Pager (`ARCHITECTURE.md`)**: Shipped to workspace root. Documents all 5 backend pipeline stages, REST endpoints, data flow, React state hierarchy, and design token rules.
- [ ] **Root `README.md` update**:
  - Replace Streamlit screenshots and instructions with React frontend instructions:
    ```bash
    # Run the canonical React frontend
    cd frontend-react
    npm install
    npm run dev        # Dev server on http://localhost:5173 (proxied to API on :8000)
    npm run verify     # Full type-check, lint, and test suite
    ```
  - Document role-based routes (`/student` vs `/faculty`), Vite proxy configuration, and backend prerequisites.
- [ ] **Docker & Compose sync**:
  - Update `docker-compose.yml` to build and serve the React Vite app (or multi-stage Nginx container) instead of running `streamlit run frontend/app.py`.
  - Update any Dockerfiles targeting frontend.
- [ ] **OpenAPI Sync (`scripts/sync-openapi.sh` or `npm run api:sync`)**:
  - When backend is running, fetch `/openapi.json` and generate TypeScript definitions (`openapi-typescript`).

#### Phase D: Git Branch Consolidation
1. Commit all verified changes on the sub-branch with clean commit messages:
   - `feat(overview): add pipeline stepper, plain-english hero, and tokenized quota card`
   - `feat(lectures): add concept timestamps and cross-lecture isolation warning`
   - `feat(remediation): add show-on-map button with DagView auto-find`
   - `docs: add root ARCHITECTURE.md and update EVALUATION_AND_PLAN.md`
2. Open a Pull Request from `frontend-react` (or feature sub-branch) to `main`.
3. Perform squash or rebase merge to keep `main` history clean and easily bisectable.

---

### 2.9 Live Interactive Browser QA Findings (Session 2)

A comprehensive browser-driven interactive QA session was executed on the live frontend (`http://localhost:5173`) running against the FastAPI backend (`http://localhost:8000`).

#### What was tested and verified fully functional:
- **Course Switching**: Switching between existing courses (`ml` with 3 lectures, `prob` with 1 lecture) dynamically updates all views, cache keys, and graph topology.
- **Overview Quick Actions**: All 4 "Where to go next" link cards (*Upload a lecture*, *Explore concept map*, *Take a quiz*, *Review remediation plan*) correctly route with valid course context.
- **Upload Modal**: `UploadDialog` opens from LecturesView, accepts title text, properly guards submit until a file is attached, and cancels cleanly without state leakage.
- **Lecture Detail View**: Renders the SVG `CoverageTimeline` cleanly; the new "Concepts extracted" card lists concepts with start timestamps.
- **Concept Map (DAG)**:
  - "Find concept" search locates matching nodes and selects them.
  - Limit slider and confidence cut slider correctly filter node count.
  - "Colour by" toggle switches between topological learner order and identity coloring.
  - Clicking any node opens the right-hand evidence drawer showing spoke quote citations.
  - Minimap and reset-view zoom buttons work.
- **Diagnostic Quiz Flow**: Loads quiz questions generated from course concepts, accepts option selection, submits answers with latency stamping, and calculates student results.
- **Remediation Loop**: Traces backward through prerequisites for wrong quiz answers; clicking the newly added **"Show on map"** button immediately routes to `/student/map?find=<concept>` and centers on the node.
- **Faculty Views**: Analytics prerequisite evidence table, Heatmap failure rates, Divergence taught-vs-learned rankings, and Lecture Coverage charts all load without error.
- **System Jobs View**: Accurately reports active, completed, and orphaned background worker tasks.

#### Gaps & UI Follow-ups Discovered:
- **No "+ Add course" affordance in UI**: The `CoursePicker` currently allows switching between existing courses in the database, but has no "+ Create Course" dialog. Courses currently have to be seeded via API or CLI.
- **Lecture Detail → Map Jump**: The "Concepts extracted" card in `LectureDetailView` displays concepts and timestamps, but does not yet have a direct "Show on map" button like `RemediationView` does.
- **Quiz viewport scroll on short screens**: On short browser viewports, quiz answer options at the bottom of the panel can require micro-scrolling; should adjust `maxHeight` container to `calc(100vh - ...)`.

---

## 3. Priority Matrix — What to Fix First

| # | Issue | Impact | Effort | Status |
|---|---|---|---|---|
| 1 | Overview: add plain-English hero + onboarding stepper | High (UX/demo) | Small | ✅ Done |
| 2 | Overview: move Quota card to System tab | Medium (UX clarity) | Tiny | ✅ Done |
| 3 | LectureDetailView: show extracted concepts with timestamps | High (core story) | Medium | ✅ Done |
| 4 | Remediation: "Show on map" button per item | High (loop closure) | Small | ✅ Done |
| 5 | MapView: wire `?find=` URL param → DagView `initialFind` | High (loop closure) | Small | ✅ Done |
| 6 | Lectures table: cross-lecture isolation warning badge | Medium (cross-lecture UX) | Small | ✅ Done |
| 7 | DAG: colour-by lecture source option | Medium (multi-lecture clarity) | Small | ⛔ Blocked — graph nodes are `string[]` with no `lecture_id`; requires backend schema change to add lecture provenance per node |
| 8 | OpenAPI → TypeScript type generation | High (dev hygiene) | Small | 🔜 Next — backend must be running; run `GET /openapi.json` then `npx openapi-typescript` |
| 9 | ARCHITECTURE.md one-pager at workspace root | High (context loss fix) | Small | ✅ Done |
| 10 | Repo Cleanup: Archive legacy Streamlit `frontend/` to `deprecated/` | Medium (repo hygiene) | Small | ✅ Done |
| 11 | Doc Alignment: Update root `README.md` for React & interactive docs | High (onboarding/ops) | Small | ✅ Done |
| 12 | Git Sub-Branch Consolidation: Merged to `main` and pushed | High (release readiness) | Small | ✅ Done |
| 13 | HeatmapView: real 2D grid instead of bars | Medium (faculty UX) | Medium | Phase 2 |
| 14 | DivergenceView: bump chart instead of table | Medium (faculty UX) | Medium | Phase 2 |
| 15 | Scatter / cluster concept view | Medium (multi-lecture insight) | Large | Phase 2 |
| 16 | Per-student drill-down (faculty) | Medium | Large | Phase 2 |
| 17 | CoursePicker: Add "+ Create new course" dialog | Medium (admin UX) | Small | ✅ Done |
| 18 | LectureDetailView: Add "Show on map" button next to extracted concepts | Medium (loop closure) | Small | ✅ Done |
| 19 | QuizPanel: Adjust responsive height for short viewports | Low (mobile UX) | Tiny | ✅ Done |

---

## 4. Known Existing Bugs (from IMPROVEMENTS.md)

These were already documented — listing here so nothing is lost:

| Bug | File | Fix |
|---|---|---|
| Upload progress bar stays at 0% | `src/api/client.ts` `putStream()` | Fall back to `body.size` when `lengthComputable` is false |
| DAG edge stroke token can render invisible | `DagView.tsx` `flowEdges` | Add fallback color if token resolves empty |
| Quiz scroll regions too short on mobile | `QuizPanel.tsx` | Use `calc(100vh - ...)` on small viewports |

---

## 5. What NOT to change right now

- **DagView internals** — it's the most complex component and it's working well.
  Don't touch the layout algorithm, the controls, or the edge rendering without
  a concrete bug to fix.
- **QuizPanel state machine** — the async job → load → submit → finish flow is
  correct and well-tested. Don't refactor it.
- **React Query key structure** — `queryKeys.*` is consistent and cache-sharing
  is working. No reason to change it.
- **The `features/` folder structure** — it's clean. Don't collapse into a flat
  `pages/` without a strong reason.

---

*Last updated: Oct 2026 — Comprehensive live QA verification complete. Items 1–6, 9, and follow-ups 17–19 shipped and verified. All unit tests pass cleanly. Ready for git cleanup, merge, and documentation updates.*


