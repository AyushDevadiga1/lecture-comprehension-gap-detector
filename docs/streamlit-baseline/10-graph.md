# 10 · Graph panel — `frontend/panels/graph.py`

**File:** `frontend/panels/graph.py` (150 lines). The course prerequisite DAG
for both dashboards: dependency-free inline SVG (see file 13) in a scroll box,
with the learner order as a badge on every node and as a contained, scrollable
study sequence.

## Shared controls (`_controls`)

Both dashboards get the same four controls:

1. **Zoom** slider (0.5–2.0); scroll inside the box to pan, drag the
   bottom-right corner to resize.
2. **Colour by** — `order` (learner order, first → last: "what do I study
   first" at a glance) or `identity` (every concept its own stable colour).
3. **Edge types** multiselect — defaults to all methods present; spoken
   transcript links (stated out loud by the professor) vs classifier links
   (inferred). Empty selection degrades to classifier-only, never to nothing.
4. **Concepts shown** slider — full graph at or under 60 nodes (`READABLE_ALL`,
   legible without filtering); above that, the significance ranking kicks in
   with a default of 40 (`DEFAULT_LIMIT`). A "Links drawn" metric shows
   kept/total edges under the current filter.

## Course view (`render_course_graph`, key prefix `sg`)

Button-gated load: `GET /courses/{id}/graph` on "Load / refresh graph", payload
kept in Tier-2 (`graph.data` + `graph.course`) so background reruns never
re-fetch it — and a payload from another course is ignored, never rendered.
Empty states distinguish three cases: never loaded (load it), loaded but
nodeless (extract concepts first), hidden-by-filter (raise the slider; the
dropped count is stated). Header line: total concepts · shown · acyclic vs
contains-cycles. `_study_sequence` renders the topological order as a numbered,
scrollable definition list (max 320 px).

## Faculty view (`render_faculty_dag`)

The same graph with its own control state (prefix `faculty`) and its own
Tier-2 slot (`faculty.graph` + `faculty.graph_course`), so the two dashboards
never share zoom/filter/selection state.
