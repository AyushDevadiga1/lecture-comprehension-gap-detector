# 13 · Stateless HTML renderers — `frontend/render.py`

**File:** `frontend/render.py` (635 lines). **Importable without Streamlit.**
Pure functions from payloads to HTML strings, unit-tested directly. Every
colour comes from `frontend.theme`; node and badge ink is always the measured
`readable_on` choice. Base-override parameters throughout make both themes
testable without running the app.

## Lecture timeline (`lecture_html`)

Turns a lecture-detail payload (`segments` + `concepts`) into a static SVG
timeline plus coverage table — "how much of the lecture is actually covered by
extracted concepts", the insight the DAG and quiz both lean on:

- track bar with transcript ticks; green `covered` windows as **one rect per
  merged run** (gaps stay visible so the graphic matches the honest `%`
  caption), via `_merge`;
- one coloured band per concept in taught order (teal→coral, the same hue ramp
  as the DAG, so a concept reads identically in both), with hover titles;
- a coverage table with each concept's window, transcript support, and the
  exact sentence used as quiz-answer evidence (`_support_sentence`).

Durations tolerate missing/garbage timestamps; non-numeric spans are skipped,
never fatal. Self-contained static HTML — no JS, no CDN — so it embeds
anywhere at zero cost.

## DAG drawing (`dag_svg`, `graph_importance`, `node_colors`)

- `graph_importance(graph, limit)` ranks concepts (well-connected, specific
  names first; keyword fragments like HAVING/update rank lowest) and splits
  kept vs dropped for the node-count slider.
- `node_colors(name, rank, total)` colours by learner-order rank or by hashed
  identity — the two "Colour by" modes from file 10.
- `dag_svg(…)` emits dependency-free inline SVG (nodes, arrowhead edges,
  learner-order badges, evidence hover text, `_legend`), so the student and
  faculty views embed it with zero page weight. A dedicated test pins "no
  external dependencies"; hostile labels are escaped.

## Interactive page (`dag_html`)

Builds the pyvis + vis-network page loaded **from a CDN**: the generated page
stays a few KB (the inlined vis.js was ~700 KB and made the view feel slow to
open), embedded via `st.iframe`. No graph nodes → a whole themed placeholder
page (a bare `<p>` would render as a white strip inside the dark app); missing
pyvis degrades to a placeholder instead of a crash.
