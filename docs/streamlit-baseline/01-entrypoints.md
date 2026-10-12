# 01 · Entry points — `student_app.py` and `faculty_app.py`

**Files:** `frontend/student_app.py` (70 lines), `frontend/faculty_app.py`
(39 lines). Run with `streamlit run frontend/student_app.py` /
`streamlit run frontend/faculty_app.py` while the backend is up.

## Design rule

Both files are **thin wiring only: they decide render order and nothing else**.
Every behaviour lives in `frontend.panels` (one module per concern) and
`frontend.client` is the only HTTP boundary. That split is what makes each
panel independently testable and what lets the layout be fixed in one place
instead of once per panel.

## Student dashboard (`student_app.py`) — render order

1. Page config (`LecGap · Student`, wide layout), title, caption.
2. **Sidebar:** `shell.course_sidebar()` → `nav_course` (the active course id,
   or `None`).
3. `shell.render_auth_banner()` → `shell.render_usage_row()` →
   `shell.render_course_snapshot(nav_course)`.
4. **Course creation (first-run path):** if no course exists, a text input
   accepts a new course ID; it is normalised with
   `client.normalize_course_id`, validated with `client.valid_course_id`
   (1–128 alphanumeric/hyphen/underscore), and the canonical key is shown back
   (`Will use canonical key …`) when it differs from what was typed.
5. **Ingest a lecture** — `ingest.render_ingest_form(upload_course)`.
6. Gate: if `nav_course is None`, warn and `st.stop()` (nothing below renders).
7. `ingest.render_process_controls(nav_course)` — extract / rebuild / cut.
8. **Concept clips** — `library.clip_watch_picker(nav_course)`.
9. `library.render_stalled_rows(nav_course)` — resumable vs abandoned rows.
10. **Course graph** — `graph.render_course_graph(nav_course)`.
11. `components.render_lecture_rows(nav_course)` — row deletion.
12. `quiz.render_quiz(nav_course)` — the diagnostic quiz.

Note the call goes through the `components` facade for lecture rows (see file
14) but directly to panel modules elsewhere — both spellings resolve to the
same functions.

## Faculty dashboard (`faculty_app.py`) — render order

1. Page config (`LecGap · Faculty`, wide), title, caption.
2. **Sidebar:** same `shell.course_sidebar()`.
3. `render_auth_banner()` → `render_usage_row()` →
   `render_progress_cards()` (no `kinds` filter — faculty sees every job on the
   course, whoever started it) → `drain_ready()` →
   `render_course_snapshot(nav_course)`.
4. Gate: if `nav_course is None`, info + `st.stop()`.
5. `faculty.render_faculty_stats(nav_course)` — heatmap + divergence.
6. `graph.render_faculty_dag(nav_course)` — the DAG with its own control state.
7. `faculty.render_faculty_timeline(nav_course)` — lecture timeline.

Loaded faculty panels persist in Tier-2 session state, so background-job
reruns never wipe them (see file 03).

## What to draw from this file

- A two-column "two apps, one backend" diagram: both entry points share the
  sidebar, banner, quota row and snapshot, then diverge into student
  (ingest → process → clips → graph → rows → quiz) vs faculty (stats → DAG →
  timeline) flows.
- A first-run vs steady-state branch: course-creation input only exists when
  no course exists; both apps `st.stop()` with no course selected.
