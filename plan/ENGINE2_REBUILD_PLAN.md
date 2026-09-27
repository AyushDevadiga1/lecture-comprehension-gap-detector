# Engine 2 Rebuild Plan — progressive, checkpointed

> **Status: PROPOSED (2026-09-27)** — supersedes the "stay on Streamlit now" call in
> `plan/FRONTEND_REACT_ROADMAP.md:3-7`. Extends that roadmap (kept as the
> architectural reference: stack §4, parity checklist §6, non-goals §8) with an
> ordered, individually-testable checkpoint sequence.
>
> **Trigger:** the confirmed UX ceiling — no loading screen, whole-script rerun
> freezing, polling-by-rerender, 6-hour spinner on a non-terminal job.

## 0. The one thing to accept before starting

The framework is **not** what fixes the wait. It fixes layout, reactivity, and
decoupling. The wait is fixed by the **backend job registry** (C2). Building the
React shell first would reproduce today's blocking calls behind prettier spinners.

Current blocking surface, measured:

| Endpoint | Behaviour today | Blocks UI? |
|---|---|---|
| `POST /lectures` | 201, row only | no |
| `PUT /lectures/{id}/media` | streamed PUT, publishes `uploading` % | upload only |
| `POST /lectures/{id}/concepts` | 201, queues worker | no |
| `POST /courses/{id}/graph` | 202, queues worker | no |
| `POST /lectures/{id}/clips` | 202, queues worker | no |
| `POST /quizzes` | **201, generates inline** | **yes — minutes** |

Plus the defects behind the "no proper loading screen" feeling:

- `progress.py:68` returns non-terminal `uploaded` forever → frontend re-renders
  every 0.5–1.5s for **6 hours** (`components.py:22`).
- Progress is keyed by `lecture_id`, held **in process memory** — a backend restart
  loses every running job, and a second tab/browser cannot see jobs it didn't start.
- No CORS middleware (`main.py`) → a Vite dev server is browser-blocked.
- Four endpoints have no spinner because Streamlit reruns the whole script.

## 1. Checkpoints

Each checkpoint ends with something **you run and click**. If a checkpoint's test
fails, stop — do not start the next one. Streamlit stays up the whole time
(roadmap §5.2: never a big-bang cutover), so there is always a working fallback.

### C0 — Stop the bleeding (keep the current app usable)
Fix, on the existing Streamlit app, before any rewrite work starts:
- `progress.py` — treat `uploaded` as a **stalled** terminal state with a reason,
  not a live job.
- `components.py` — add a no-progress cutoff (~20 unchanged polls) so no state can
  spin indefinitely.
- `components.py:26` — lock `_UPLOADS`; it is an unlocked global written by the
  upload thread and read by the script thread.
- Disable a job's buttons while it is in flight.
- Extend `PIPELINE_SEMAPHORE` past transcription (only `transcribe.py:19` takes it
  today) to concept/graph/clip workers.
- Guard `POST /quizzes` against concurrent generation for one course.

**You test:** upload a lecture, watch stages, refresh mid-job, click around during
a job. No multi-minute flicker. Buttons can't be double-fired.

### C1 — Fix test isolation for good
`config.py` freezes `DATABASE_URL` at import and 21 test files never overrode it, so
the suite wrote into the live DB. Partially done (lazy `database_url()` + conftest
temp DB + collection guard). Finish it: add `pytest` markers so backend tests can
point at fixtures without touching `data/`, and assert no `data/*.db` appears in CI.

**You test:** `python -m pytest tests` twice; `data/` is byte-identical after.

### C2 — Backend job registry (the real fix for the wait)
Replace fire-and-forget `BackgroundTasks` with persisted jobs.
- New `jobs` table: `id`, `kind`, `course_id`, `lecture_id`, `status`
  (`queued → running → ready | error | orphaned`), `progress_pct`, `stage`,
  `detail`, `created_at`, `started_at`, `finished_at`, `heartbeat_at`, `error`.
- `POST /jobs` → `202 {job_id}`. `GET /jobs?course_id=` (all sessions see all jobs).
  `GET /jobs/{id}`. `DELETE /jobs/{id}`.
- Progress published by `job_id`, not `lecture_id`. Survives backend restart —
  on boot, `running` jobs past their heartbeat become `orphaned`.
- **Per-course advisory lock**: one extraction/clips/graph job per course at a
  time, so two users can't interleave on the same DAG.
- `POST /quizzes` becomes `202 + job_id` (this is the endpoint that blocks today).
- Workers take the semaphore from `common.py` uniformly.

**You test:** start a transcribe job, restart the backend mid-job → the job shows
`orphaned`, not a silent hang. Open two browsers → both see the job. Quiz
generation returns instantly and shows progress.

### C3 — Quiz idempotency
`POST /quizzes` must stop delete-and-recreate churn (`quizzes.py:162`). Version-stamp
`ConceptItem`; submit echoes the version; a stale version returns a friendly
"regenerated" instead of a 404 dead end.

**You test:** two browsers generate a quiz for the same course; the first student's
in-flight answers still submit successfully.

### C4 — Contract v2
- CORS middleware (allow-list the dev origin).
- Payloads emit **URLs**, never filesystem paths — the frontend stops doing the
  `path → /media/...` mapping that `client.py:327-350` does today.
- Document `jobs` + the `{detail}` error envelope; bump contract version.
- OpenAPI snapshot test so drift fails CI.

**You test:** `curl` the OpenAPI JSON; every payload has `url` not `path`.

### C5 — React scaffold
Vite + React 18 + TypeScript, `react-router` (`/student`, `/faculty`), React Query,
zustand, MUI. Typed API client generated from the C4 contract. Dev proxy → `:8000`.
**No features yet** — one page per role that lists courses from the live DB.

**You test:** `npm run dev`, open `/student` and `/faculty`, both list `ml` and
`prob` with real counts. F12 shows no CORS error.

### C6 — Student upload + live progress (the showcase fix)
- Chunked upload with **real** progress (XHR `upload.onprogress`, not a spinner).
- Job cards driven by `GET /jobs` — multi-job, survives refresh/navigation,
  visible across browsers, terminal states stop cleanly (C0's bug cannot recur —
  the registry is the source of truth, not process memory).
- Course select/refresh/delete with correct React Query invalidation.
- Clear empty/loading/error states for every panel.

**You test:** upload a real lecture; the bar moves during upload *and* through
stages; navigate to faculty and back — still attached; open a second browser — job
visible. This is the checkpoint that must eliminate your original complaint.

### C7 — Faculty dashboard
Interactive DAG (react-flow, hover an edge for the professor's exact sentence),
heatmap, taught-vs-learned divergence, per-lecture timeline/coverage. Panels persist
across navigation.

**You test:** roadmap §6 faculty checklist, item by item.

### C8 — Quiz + remediation
Async generation, draft survives navigation and background polling, submit →
score/feedback, remediation `<video>` in learner order (Range streaming already
works server-side).

**You test:** generate a quiz, start a lecture job mid-quiz, finish the quiz —
nothing was regenerated or lost. Play a remediation clip.

### C9 — E2E + cutover
Playwright over both dashboards; then flip the proxy default to the React build.
Streamlit entrypoints retired only after parity passes.

## 2. Non-negotiables carried from the roadmap
- No big-bang cutover; Streamlit runs throughout (C0–C9).
- No SSR/Next.js, no microfrontends, no state sync back to the Python apps.
- No retraining/ML-evaluation rewrites.
- Errors are always the `{detail}` envelope; 401 is one banner, never a dead
  "no courses" state.

## 3. Honest risk
`plan/TEAM.md` flags solo-execution risk, and the roadmap's own trigger (§2) prices
this as a **3–6 week solo detour**. C0–C4 are backend work and are the part that
actually improves the product; C5–C8 are comparatively mechanical. If time is short,
stop after **C4** — that alone delivers job transparency, cross-user visibility,
restart safety, and non-blocking quiz generation, and the existing Streamlit UI
becomes usable instead of frustrating.

## 4. On the "beats NotebookLM" framing
Calibrate this honestly: the framework is not the differentiator. NotebookLM will
ship a better loading screen than we do in C6. What is genuinely hard to copy here
is the **prerequisite DAG with spoken-evidence edges** (hover an edge → the exact
sentence the professor said, `source_method: transcript @0.90`) and the
**taught-vs-learned divergence** that falls out of it. C7 and C8 exist to make
*that* visible. A new framework is what makes it presentable; it is not what makes
it better.
