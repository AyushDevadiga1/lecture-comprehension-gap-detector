# LecGap · Streamlit Baseline — Model Context

> **What this is.** A complete, codebase-free description of the Streamlit
> version of LecGap (Lecture Comprehension Gap Detector) as baselined on the
> `main` branch at commit `5e0a434`. It is written so that a model — or a person
> — can answer questions, draw architecture diagrams, and draft presentations
> about the system **without opening the code**.
>
> **Scope.** Everything under `frontend/` on `main` (the Streamlit engine), the
> backend surface it depends on, the theme system, and the tests that pin it.
> The React rebuild on `engine2/scaffold` is deliberately out of scope.
>
> **How to use this folder.** Start here for the map, then read the numbered
> files one by one. Each file is self-contained: purpose, responsibilities, key
> functions, mechanics, and failure modes. File `18` contains copy-pasteable
> Mermaid diagrams and a slide outline for presentations.

## The system in one paragraph

A lecturer uploads a recorded lecture. The backend transcribes it (Whisper),
extracts concepts and spoken prerequisite links, builds a course concept graph
(DAG), and cuts short remediation video clips per concept. A student takes a
capped diagnostic quiz; wrong answers trace prerequisites backwards into a
personalised, dependency-ordered remediation plan with clips. Faculty see a
confusion heatmap, taught-vs-learned order divergence, and the DAG. The
Streamlit frontend in `frontend/` is a thin two-dashboard UI over a FastAPI
backend; all heavy work runs as durable backend jobs, watched live over
server-sent events.

## Module map

| # | File | One line |
|---|------|----------|
| 01 | `frontend/student_app.py`, `frontend/faculty_app.py` | The two entry points; thin ordering-only wiring |
| 02 | `frontend/client.py` | HTTP boundary, error model, Tier-1 TTL cache, media URLs, uploads |
| 03 | `frontend/state.py` | Tier-2 session-state namespaces (`nav/quiz/faculty/jobs/tl`) |
| 04 | `frontend/theme.py` | The single colour system: tokens + measured contrast |
| 05 | `frontend/layout.py` | Shared HTML primitives: scroll boxes, cards, escaping, video frames |
| 06 | `frontend/jobfeed.py` | SSE job feed with polling fallback; one connection per process |
| 07 | `frontend/panels/shell.py` | App chrome: sidebar, quota row, upload threads, job monitor, snapshot |
| 08 | `frontend/panels/ingest.py` | Upload form + duplicate guard + the three pipeline actions |
| 09 | `frontend/panels/library.py` | Clip players, stalled-row triage, lecture-row deletion |
| 10 | `frontend/panels/graph.py` | Course/student and faculty DAG views + study sequence |
| 11 | `frontend/panels/quiz.py` | Capped generation, answering, submit, feedback, remediation |
| 12 | `frontend/panels/faculty.py` | Heatmap, divergence, lecture timeline |
| 13 | `frontend/render.py` | Streamlit-free HTML/SVG renderers: timeline, DAG, pyvis page |
| 14 | `frontend/components.py` | Facade re-exporting the panel API (refactor without API change) |
| 15 | — | Backend surface the frontend depends on (endpoints, contracts) |
| 16 | — | Test files and what each one pins |
| 17 | — | Known gaps (verified, not rumours) |
| 18 | — | Mermaid diagrams + presentation outline |

## How to run it (baseline)

```bash
# terminal 1 — backend on :8000
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# terminal 2 — student dashboard
streamlit run frontend/student_app.py

# terminal 3 — faculty dashboard (same backend, same database)
streamlit run frontend/faculty_app.py
```

Configuration lives in environment variables: `LECGAP_API_URL` (default
`http://127.0.0.1:8000`, must be http/https with a host),
`LECGAP_API_KEY` (sent as `X-API-Key`; optional),
`LECGAP_QUIZ_MAX_QUESTIONS` (default 15). The theme is declared in
`.streamlit/config.toml` (`base = "dark"`); `frontend/theme.py` derives every
colour from it.

## The two-tier state model (the single most important idea)

Streamlit re-executes the whole script on every interaction, so state that must
survive a rerun lives in exactly two places, and nowhere else:

- **Tier 1 — `client.py` `CacheStore`.** Process-wide, TTL-keyed HTTP cache.
  Reads (`/courses`, `/lectures`, `/snapshot`, …) go through it with
  per-endpoint TTLs (5 s for the live snapshot, 300 s for graphs). Mutations
  clear it through one rule, `invalidate_for_course()`. Values are returned as
  deep copies so callers cannot poison the cache.
- **Tier 2 — `state.py` namespaces in `st.session_state`.** Per-session UI
  state: `nav`, `quiz`, `faculty`, `jobs`, `tl`. Every key is prefixed
  `lecgap:`.

Background liveness comes from two more pieces: `jobfeed.py` (an SSE-fed
in-memory job snapshot, one connection per process) and the `st.fragment`
progress cards in `shell.py` (only the card block re-executes each second, so
`<video>` players elsewhere never restart). Completion announcements are
recorded in Tier-2 and rendered by `drain_ready()` in the page body — never
inside the fragment, where they would flash and vanish.

## Request flow (upload → remediation)

1. **Create row** — `POST /lectures` with `{course_id, title}` (form-encoded).
2. **Stream media** — `PUT /lectures/{id}/media` in 1 MiB chunks with
   `Content-Length`; cancellable between chunks. The PUT enqueues the durable
   transcription job and returns its `job_id`.
3. **Watch** — the SSE feed (`GET /jobs/stream`, fallback `GET /jobs`)
   publishes progress; `st.fragment` cards re-render each second.
4. **Extract** — `POST /lectures/{id}/concepts` → job.
5. **Graph** — `POST /courses/{id}/graph` (auto after extract; rebuildable).
6. **Clips** — `POST /lectures/{id}/clips` → `GET /lectures/{id}/clips`;
   playback is via `GET /media/clips/{lecture_id}/{filename}` (byte-range
   capable), never a filesystem path.
7. **Quiz** — `POST /quizzes` (capped, blocking), answer, `POST
   /quizzes/submit` → score + per-question feedback + ordered remediation with
   clips.
8. **Faculty** — `GET /courses/{id}/stats` (heatmap + divergence),
   `GET /courses/{id}/graph` (DAG), lecture timeline from `GET /lectures/{id}`.

## Conventions a reader must know

- **Panels ask for meanings, never colours.** Every colour comes from
  `theme.current()` tokens (`text`, `muted`, `border`, `surface`, `ok`, `warn`,
  `bad`, `info`, …). Foreground ink is *measured* (`readable_on`), never
  eyeballed; `tests/test_theme.py` pins WCAG AA per token per surface.
- **User data is escaped at the HTML boundary** (`layout.escape`); `scroll_box`
  takes trusted markup and the caller is responsible.
- **Long content scrolls inside its own box**, never by stretching the page
  (`layout.scroll_box`, default 420 px).
- **Errors surface as `{detail}` text**, never tracebacks
  (`client.take_last_error()` → inline `st.error`/`st.warning`).
- **One pipeline job at a time per lecture** — action buttons disable while a
  job is running (`shell.active_job`), so duplicate work can't be queued.
- **Course IDs are canonicalised** for new courses (`strip → UPPER →
  whitespace→'-'`); existing keys in any case stay readable.
