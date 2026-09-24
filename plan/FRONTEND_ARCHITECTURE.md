# Frontend Architecture — Streamlit engine (split, cache, state, media)

> **Status: AGREED (2026-09-24)** — design signed off in session; docs written.
> **Implementation is deliberately gated**: nothing below is implemented until the
> owner triggers it ("sos"). This doc is the *contract* for the current Streamlit
> engine; the future React engine is specified separately in
> `plan/FRONTEND_REACT_ROADMAP.md`.
> Both depend on `plan/FRONTEND_API_CONTRACT.md`, which this design never bypasses.

## 1. Why this exists

The frontend audit (2026-09-24, session) found the single `frontend/app.py` (542
lines, two tabs) has production-breaking defects that cluster into four roots:

1. **No persistent UI state** across Streamlit reruns — quiz questions, faculty
   stats and the DAG are held in function locals bound to a form-submit flag, so
   the background-job poll loop (`st.rerun()` every 0.5–1.5 s) silently erases a
   student's active quiz mid-answer and drops loaded DAG/stats.
2. **No true separation** between the student and faculty surfaces — one
   anonymous app, one progress slot (`lecgap_job`), destructive actions reachable
   by anyone, no cache-isolation between the two audiences.
3. **Cache/key bugs** — deleting a course leaves it listed until TTL expiry;
   cache invalidation is event-driven only through the progress monitor; the
   frontend never sends an API key, so a guarded backend 401s and the UI degrades
   to a misleading "No courses yet".
4. **Broken media playback** — remediation clips are handed to `st.video` as
   server filesystem paths; there is no media-serving endpoint, so the browser
   404s and the flag feature doesn't play.

This doc fixes all four for the Streamlit engine and — importantly — does it so
that a later React frontend can consume the *same* backend contract with the
same caching semantics (see `plan/FRONTEND_REACT_ROADMAP.md`).

## 2. Goal and non-goals

**Goals:**
- Two independent Streamlit entrypoints (student, faculty) sharing one
  pure-Python API client + cache layer, each with its own UI state.
- A two-tier cache: Tier-1 read cache (TTL, global across sessions) and Tier-2
  per-session UI state, with one invalidation rule.
- All audit defects above fixed and covered by tests.
- Lock the HTTP contract so a React rewrite is a leaf replacement.

**Non-goals (locked, out of scope for this engine):**
- No React / non-Streamlit frontend in this engine (spec in the REACT_ROADMAP).
- No backend job-registry / job IDs / persisted progress queue — the progress
  model stays `lecture_id`-keyed. Frontend monitor becomes a multi-job *list* so
  multiple cards show, but cross-user progress is still best-effort. The job
  registry is a hard precondition for the React engine (REACT_ROADMAP §3).
- No authentication/roles inside the app. Separation is by *entrypoint and URL*
  only this phase; auth moves to the reverse-proxy layer in the React engine.
- No quiz engine rework (versioned ids / idempotent generation) — that is a
  backend follow-up documented in the REACT_ROADMAP. This engine only makes the
  frontend *handle today's* quiz races gracefully (friendly "regenerate", never a
  traceback).
- No charting/DAG framework change in this engine (`render.py` stays pyvis/SVG).

## 3. Target structure

```
frontend/
├── client.py       # NEW  pure-Python API client + CacheStore   (NO streamlit import)
├── state.py        # NEW  namespaced session-state helpers      (Streamlit-bound, thin)
├── render.py       # KEEP  pure HTML builders (dag_html, lecture_html) — unchanged
├── components.py   # NEW  shared UI: progress card(s), quiz flow, coverage table
├── student_app.py  # NEW  student dashboard entrypoint
└── faculty_app.py  # NEW  faculty dashboard entrypoint
# frontend/app.py REMOVED after M2 parity is proven
```

Design rule (the swap-enabler): **`render.py` and `client.py` never import
Streamlit.** Everything Streamlit-specific lives in `state.py`, `components.py`
and the two entrypoints. That keeps the expensive/business logic unit-testable
with zero stub machinery and makes the framework a replaceable leaf.

### 3.1 `client.py` — API client + Tier-1 cache

Pure Python (stdlib + `requests`). Responsibilities:

- **Base URL**: reuse the validated-URL logic from current `app.py:_validated_api_url`
  (`LECGAP_API_URL`, http/https + host only).
- **Auth**: send `X-API-Key` from `LECGAP_API_KEY` on every request when set.
  A `401` result is never silently swallowed — it surfaces via a status marker
  the app renders as one top-level banner ("Backend requires API key").
- **Transport seam**: the module exposes `get/post/delete` that call an internal
  `_request`; tests and `AppTest` replace the transport or the clock, never the
  app script.
- **Error envelope**: on any 4xx/5xx, always try `json()["detail"]` and surface
  that text (current `_get` drops it — audit C-2). Transient connection errors
  get one retry (1 s) before surfacing.
- **Timeout policy**: reads 30 s, writes: upload 600 s, quizzes 600 s with the
  existing "may still be running" wording.
- **CacheStore**: keyed by (method, path, sorted params). `ttl()` per call-site
  (60 s lists, 300 s heavy reads). Explicit `invalidate(prefix)` and
  `invalidate_all()`. Stored value carries an `as_of` timestamp so TTL is checked
  *inside* the cache, making `persist="disk"` safe to layer on later. No mutation
  on cached payloads (the store returns copies, and callers must not mutate
  shapes).
- **Injectable clock** (`time.monotonic` default) so TTL tests are deterministic.

### 3.2 Two-tier cache + invalidation rule

| Tier | Store | Scope | Holds |
|---|---|---|---|
| 1 Data | `client.CacheStore` (module singleton, TTL) | shared across sessions within one Streamlit process | `/courses`, `/lectures`, `/lectures/{id}`, `/clips`, `/stats`, `/graph` — 60 s lists / 300 s heavy reads |
| 2 Session | `state.py` over `st.session_state` | per user | active quiz(+ids, version, render-t), loaded stats, loaded DAG, job monitor **list**, `nav_course`, selected lecture, media URLs |

**Cache semantics note:** the client is pure Python, so the Tier-1 store is a
TTL dict *owned by the module* (`client`), shared by every session in the same
Streamlit process. Each dashboard (`student_app.py`, `faculty_app.py`) is its own
process and therefore has its own warm cache; the 60 s/300 s TTL plus manual
invalidation keeps cross-process staleness bounded. Cross-process sharing via
`persist="disk"` is a later optimization, not needed for correctness.

**Invalidation rule — one function, used everywhere a mutation happens**
(`client.invalidate_for_course(course_id)`):
course/lecture lists cleared always + course-scoped keys (stats/graph/clips/detail)
cleared for that course. Call sites: upload success, course delete, lecture
delete, transcript ready, extract ready, graph ready, clips ready, manual
"Refresh course list" button. This fixes the audit's stale-list-after-delete bug
because every mutation path now clears caches explicitly, not as a side effect of
the progress monitor.

### 3.3 `state.py` — Tier-2 session state helpers

Thin, Streamlit-bound, namespaced helpers:

```
state.get_state(ns)      -> dict for namespace (created on demand)
state.set(ns, **kv)      / state.clear(ns)
```

Namespaces (single source of truth, documented here):
- `nav` — `course`, last-loaded course for data panels
- `quiz` — `questions`, `version`, `render_t`, `course_id`, `student_id`
- `faculty` — `stats`, `graph`, per-course cache stamp
- `jobs` — `items: [ {lecture_id, title, kind, after} ]`  ← multi-job, replaces `lecgap_job`
- `tl` — selected lecture + rendered timeline key

Entrypoints hydrate/persist these; reruns read from them. This is what makes the
quiz and the faculty panels survive the progress-poll reruns (audit C-1/C-3).

### 3.4 `components.py` + entrypoints

`components.py` holds render helpers that touch `st.*` but are otherwise dumb:
`render_progress_cards(jobs, client)` (one card per job in the `jobs` namespace,
adaptive backoff from current `_monitor_progress`), `render_quiz(state, client)`,
`render_course_sidebar(state, client)` with the upload *locked to the selected
course* (audit C-5). Entrypoints are thin scripts that only wire widgets →
`state.py`/`components.py`/`client.py`.

## 4. Correctness fixes folded in (audit → fix)

| # | Audit defect | Fix in this engine | Tests |
|---|---|---|---|
| 1 | Quiz wiped by job-poll rerun | Persist quiz in `state['quiz']`; render from state, not from the submit flag | L2 regression |
| 2 | Stats/DAG vanish between reruns | Persist loaded payloads in `state['faculty']`, stamped per course | L2 |
| 3 | Deleted course stays listed | `invalidate_for_course()` after delete; sidebar re-scopes | L2 |
| 4 | API key never sent / 401 silent | `X-API-Key` header + first-class 401 banner | L1 |
| 5 | Upload silently targets a different course | Upload course id locked to sidebar selection | L2 |
| 6 | Single progress slot overwritten | `jobs` list — each started job adds a card | L2 |
| 7 | Remediation clip never plays | New backend media endpoint (§6) → `st.video(media_url)` | L2+L3 |
| 8 | GET 4xx detail dropped | `client` surfaces `detail` on reads too | L1 |
| 9 | Quiz-race raw 404 | Submit 404 → "quiz regenerated — generate again" message, no traceback | L2 |

## 5. Fresh-start visibility (transparency between users)

Even without a backend job registry, a user who opens a dashboard while a job is
running **can** see it: on first render, the student dashboard polls
`GET /lectures/{id}/progress` for the course's non-`ready` lectures and seeds the
`jobs` list. Same mechanism the monitor already uses; just framed for "attach to
existing job" instead of "job I started." Cross-user concurrency limits (shared
progress slot per lecture) are documented limitations, not regressions.

## 6. Backend addition (the only backend change this phase)

`GET /media/clips/{lecture_id}/{filename}` — streams the clip file from
`data/processed/clips/{lecture_id}/` with `Range` support (FastAPI `FileResponse`).
Returned as a URL (`/media/...`) from the existing clips endpoints and quiz
remediation payloads is *out of scope*: **this phase keeps payload paths as-is**
and the frontend maps `path → media_url` when rendering (one function in
`client.py`). Changing the schema would break the contract doc; instead the
contract doc lists the media endpoint as the canonical playback URL and maps at
the edge. Full schema change to emit URLs is deferred to the REACT_ROADMAP's
contract v2.

## 7. Milestones and definition of done

| # | Deliverable | Done when | Gate |
|---|---|---|---|
| M1 | `client.py` + `state.py`, no UI change | Unit tests green; existing `app.py` still runs untouched | L1 |
| M2 | `components.py`, `student_app.py`, `faculty_app.py`; delete `app.py` | Every flow in old `app.py` present in the split apps (parity checklist §8.4) | L2 |
| M3 | Fixes 1–9 incl. backend media endpoint | All regression tests green | L1+L2+L3 |
| M4 | Test-suite polish + CI config (optional, on go-ahead) | `pytest` green; smoke script extended | L3 |

## 8. Test plan (three levels)

### 8.1 L1 — Unit (pytest, hermetic, no Streamlit runtime)
- `tests/test_client.py`: URL validation; auth header injection; retry/backoff;
  timeout + HTTP error → `None` with `detail` surfaced; 401-not-silent flag;
  CacheStore keying, TTL (fake clock), invalidate(prefix) / invalidate_all,
  COPY semantics (mutating a returned payload must not poison the cache),
  `persist="disk"` version-stamp guard.
- `tests/test_state.py`: namespacing get/set/clear; unknown-namespace defaulting.
- `tests/test_frontend_render.py`: unchanged (existing pyvis/SVG tests).

### 8.2 L2 — AppTest (`streamlit.testing.v1.AppTest`, Streamlit 1.62)
- `tests/test_student_app.py`:
  - sidebar course renders; upload locked to selected course (assert no text-input
    that can drift — upload course is not user-editable);
  - **quiz survives a rerun** (run script, generate quiz, then `.run()` again with a
    `requests`-transport that only serves the quiz GETs — assert question + radio
    widgets still present); submit renders score/feedback; remediation renders
    media **URLs** (assert the string contains `/media/clips/...`);
  - progress card seeds for an unattached in-flight lecture and shows for a
    started job; starting a second job doesn't drop the first (both cards).
- `tests/test_faculty_app.py`:
  - stats persist across a plain rerun; DAG present after load (assert node names
    in the embedded HTML via `at.get("components.html")`/document); selecting
    another lecture invalidates the timeline detail; `None` taught/learned indices
    render as `—`.
- Transport/library note: `file_uploader` and `form_submit_button` are supported
  in AppTest on 1.62; `st.video`/charts are not assertable — assert the URL/data
  strings instead, then cover real playback in L3.

### 8.3 L3 — Live smoke + manual pass
- Extend `scripts/smoke_ui.py` (seed) + `scripts/smoke_drive.py`:
  - drive both entrypoints' exact HTTP call sets against the seeded smoke DB;
  - verify the media endpoint streams: 200 + `Accept-Ranges: bytes` on a byte
    range request;
  - one manual checklist run of `streamlit run frontend/student_app.py` and
    `frontend/faculty_app.py` covering: upload→transcribe card, quiz survive-
    rerun, remediation video plays, DAG renders.

### 8.4 Parity checklist (M2 gate)
Every flow present in `app.py` must exist in the split apps:
1. Upload + transcribe (progress card, cache invalidate)
2. Extract concepts + build graph (card, graph auto-rebuild)
3. Rebuild graph only (with `lecture_id` progress)
4. Cut concept clips (+ `clips_list` follow-up)
5. Quiz generate → answer → submit → feedback + remediation + playback
6. Course select / refresh / delete (cache invalidation)
7. Faculty stats (heatmap + divergence)
8. Faculty DAG + learner order
9. Faculty timeline + coverage (per-lecture detail)
10. Empty / no-courses states everywhere (no tracebacks)

## 9. Deferred (explicitly out of this engine)

- Backend job registry (job IDs, persisted progress, per-course advisory lock,
  orphan detection) → REACT_ROADMAP §3 precondition.
- Quiz idempotency / versioned question ids → same.
- Auth/RBAC → reverse-proxy layer, React engine.
- Frontend framework change → REACT_ROADMAP.