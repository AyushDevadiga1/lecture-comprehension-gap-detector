# 12 · Faculty analytics — `frontend/panels/faculty.py`

**File:** `frontend/panels/faculty.py` (100 lines). Read-only analytics with no
in-flight state, kept apart from the student panels so the student path can be
reasoned about (and tested) without dragging faculty views along.

## Stats (`render_faculty_stats`)

Button-gated `GET /courses/{id}/stats`, payload in Tier-2 (`faculty.stats` +
`faculty.stats_course`), course-scoped like the graph.

- **Confusion heatmap** — wrong-answer rates, highest first, as monospace
  block bars (`█` × rate·10) in `bad`, with `wrong/attempts` in muted. No
  graded answers yet → "students must submit a quiz first" caption, not an
  empty chart.
- **Divergence** — per concept, `taught #i vs learned #j` with an arrow (`→
  later`, `← earlier`, `=`), tolerating missing indices (`—`, never a crash on
  `None`).

Both lists scroll inside their own 320 px boxes.

## Timeline (`render_faculty_timeline`)

"How much of the spoken lecture the extracted concepts actually pin down."
Ready-lecture picker (shared `library` helpers), selection in Tier-2 `tl`,
detail via `GET /lectures/{id}` (failure → warning with `{detail}`, never a
traceback), rendered through `render.lecture_html` (file 13) as an SVG
timeline plus per-concept quiz-evidence sentences.
