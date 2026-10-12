# 03 · Tier-2 session state — `frontend/state.py`

**File:** `frontend/state.py` (44 lines). Streamlit-bound but thin: the only
Streamlit API it touches is `st.session_state`.

## The contract

Every piece of UI state that must survive a rerun lives in a **namespace**
under `st.session_state`, with keys prefixed `lecgap:`. The namespaces
(contract with `plan/FRONTEND_ARCHITECTURE.md` §3.3):

| Namespace | Holds |
|---|---|
| `nav` | course, last-loaded course for data panels |
| `quiz` | questions, version, `render_t`, `course_id`, `student_id`, result, error, cap |
| `faculty` | stats, graph, per-course cache stamps (`stats_course`, `graph_course`) |
| `jobs` | `items` (monitor cards: lecture/title/kind/after), `completed` (announcements) |
| `tl` | timeline: selected lecture + rendered timeline key |
| `clips_view` | which lecture's clips are open in the watch picker |

## API (four functions)

- `get_state(ns)` — return the namespace dict, creating it on first access.
- `get(ns, key, default)` — read one value.
- `set(ns, **kv)` — merge values in.
- `clear(ns)` / `clear_all()` — drop one namespace / every `lecgap:` key.

## Why namespaces instead of bare keys

A flat `st.session_state` is a global variable with no owner: two panels can
claim the same key and one rerun wipes the other's work. Namespaces make
ownership visible (`quiz` questions belong to the quiz panel), make
course-scoping checkable (graph payloads carry their `course` and are ignored
for other courses), and make clearing safe (course switch clears `quiz`
without touching `jobs`).

## Testability

Tests replace the module-level `st` with a stub exposing a dict
`session_state`, since the module only ever touches `st.session_state`
(`tests/test_state.py`).
