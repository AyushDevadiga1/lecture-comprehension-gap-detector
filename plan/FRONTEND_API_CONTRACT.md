# Frontend API Contract — locked HTTP surface for both engines

> **Status: AGREED (2026-09-24)** — frontend↔backend boundary. Both the Streamlit
> engine (`plan/FRONTEND_ARCHITECTURE.md`) and the future React engine
> (`plan/FRONTEND_REACT_ROADMAP.md`) consume ONLY what is documented here. The
> frontend never imports `backend/*` (see `plan/ARCHITECTURE.md`, decoupled
> architecture). Schema source of truth: `backend/api/schemas.py`. Version: **v1**.

## 1. Global rules

- **Base URL**: `LECGAP_API_URL` (default `http://127.0.0.1:8000`), http(s), host required.
- **Auth**: when the backend runs with `LECGAP_API_KEY` set, every route except
  `/health`, `/docs`, `/openapi.json`, `/redoc` **and `/media/*`** requires
  `X-API-Key: <key>` or `Authorization: Bearer <key>`; wrong/missing →
  **401** `{"detail":"Unauthorized"}`. The frontend sends `X-API-Key` from its
  own `LECGAP_API_KEY` when set. `/media/*` is exempt because a browser
  `<video>`/`st.video` cannot attach the header; real deployments gate `/media`
  at the reverse proxy / CDN (see REACT_ROADMAP §4-auth).
- **Error envelope**: non-2xx bodies carry `{"detail": <str>}` (Pydantic 422 may
  include a `detail` list of validation errors). Frontends must extract and
  display `detail` verbatim, never a raw traceback.
- **Unexpected errors**: unhandled exceptions → **500** `{"detail":"Internal
  server error"}` (details only in server logs, never echoed).
- **Content**: all payloads JSON. File uploads via `multipart/form-data`.
- **Versioning**: breaking payload changes bump this contract's version; the old
  shape stays served during one migration window.

## 2. Endpoints

### Reads (cacheable)

| Method + path | Request | Response | Errors |
|---|---|---|---|
| `GET /courses` | — | `List[CourseSummaryOut]` | — (empty list if none) |
| `GET /lectures?limit=&offset=` | limit=`int`≥1 (default 500), offset=`int`≥0 | `List[LectureOut]` | 400 bad int; 422 |
| `GET /lectures/{id}` | path int | `LectureDetailOut` (segments+concepts) | 404 `"Lecture not found"`; 422 |
| `GET /lectures/{id}/progress` | path int | `LectureProgressOut` — **always 200** for valid id; "not found" is a *status field*, not HTTP | 422 |
| `GET /lectures/{id}/clips` | path int | `ClipBatchOut` (status `"ready"`) | 404; 422 |
| `GET /courses/{id}/graph` | `id` matches `[\w\-]{1,128}` | `CourseGraphOut` | 404 `"No graph for this course"`; 422 |
| `GET /courses/{id}/stats` | `id` regex above | dict: `course_id`, `heatmap[]`, `divergence[]`, `taught_order[]`, `learned_order[]` | 422 (never 404) |
| `GET /courses/{id}/snapshot` | `id` regex above | dict: `exists`, `lectures{total,ready,uploaded,transcribing,error}`, `concepts`, `graph{has,nodes,edges}`, `clips{cut,ok}`, `quiz{questions,respondents}`, `in_flight[{lecture_id,title,status,stage,progress_pct}]` — derived readiness; the frontend's 5s consistency layer | 422 (never 404) |
| `GET /usage` | — | `{services:{groq.chat, groq.whisper, local, ollama}, availability}` — live per-service Groq rate-limit leftovers (`remaining_requests`, `remaining_tokens`, `reset_in_s`), honest absence when no call happened yet; **guarded** like `/llm/backends` | 401 via middleware |
| `GET /health` | — | liveness (public, no auth) | — |

**Progress semantics** (`LectureProgressOut`): live `status` values during work are
`transcribing` (transcribe/extract/etc. — backend keeps this as the live state
string) with a `stage` giving finer granularity; `progress_pct` 0–100; `detail`
human text; `elapsed_s` since job start; `duration_s?` the probed media length,
published once the transcribe worker passes ffprobe (drives the quota estimate);
`updated_at` ISO. Terminal states the frontend acts on: `ready` (100), `error`,
`not_found` (lecture row gone). After a backend restart, live progress is lost
and the DB fallback reports `transcribing/50` (stuck) or `ready` (stale) —
Engine-2 requires the job registry to fix this; Engine-1 must render these
honestly.

### Writes (mutate → invalidate caches)

| Method + path | Request | Response | Errors |
|---|---|---|---|
| `POST /lectures` | multipart: `file` (optional now), `course_id` (required form), `title?`, `whisper_backend?` (“local”\|“groq”). **With `file`**: legacy single-shot (201, transcribe scheduled). **Without `file`** (two-step): creates the row fast with status `"uploaded"`, no media, no job | **201** `LectureOut` | 400 bad extension / bad backend / invalid filename; 413 upload cap; 422 |
| `PUT /lectures/{id}/media?filename=&whisper_backend=` | streamed raw body with `Content-Length`; backend writes chunks + publishes `uploading` progress, then schedules transcription | `LectureOut` | 400 bad extension / missing Content-Length; **409** `must be 'uploaded'`; 404; 413 cap; 422 |
| `POST /lectures/{id}/concepts` | — | `LectureDetailOut`; extraction+graph run in background | 404; **409** `must be 'ready' before extraction`; 422 |
| `POST /courses/{id}/graph?lecture_id=` | optional `lecture_id` int (attaches progress) | **202** `CourseBuildOut` (`status:"queued"`) | 422 (no 404 — worker no-ops on empty course) |
| `POST /lectures/{id}/clips` | — | **202** `ClipBatchOut` (`status:"queued"`) | 404; **409** `must be 'ready' to cut clips`; **409** no concepts yet; 422 |
| `POST /quizzes` | `{course_id, student_id}` (both `[\w\-@.]`≤128, course `[\w\-]`) | **201** `QuizOut` (shuffled options, answer never included); **blocking, can take minutes, and deletes+recreates the course's question rows** | 404 `"No concepts for course"`; 422 |
| `POST /quizzes/submit` | `{course_id, student_id, answers:[{question_id, selected?, latency_s?}]}` | `QuizSubmitOut` (graded server-side; answer/correct fields ignored if sent) | 404 `"Question {id} not found"`; **400** cross-course answer; 422 |
| `DELETE /courses/{id}` | — | `CourseDeleteOut` (removes rows+media+clips) | 404; 422 |
| `DELETE /lectures/{id}` | — | `LectureDeleteOut` (cascades + media) | 404; 422 |
| `POST /lectures/{id}/rerun` | — | `LectureOut` (re-queues transcription) | 400 source missing; 404; 422 |

### Media (added by Engine-1 M3; canonical playback URL for both engines)

| Method + path | Request | Response | Errors |
|---|---|---|---|
| `GET /media/clips/{lecture_id}/{filename}` | path int + sanitized filename | `FileResponse` streaming with **Range** support (`Accept-Ranges: bytes`); serves from `data/processed/clips/{lecture_id}/` | 404; 422 |

**Frontend mapping rule (v1):** clips/remediation payloads currently return the
*server filesystem path* (`ClipOut.path`, `WatchItemOut.clip`). The frontend maps
`path → /media/clips/{lecture_id}/{filename}` at the edge via one helper
(`client.media_url`). Contract v2 (React engine) will emit URLs directly.

## 3. Response shapes (v1)

```text
LectureOut        id, course_id, title, status, error?, created_at, processed_at?
SegmentOut        idx, start_s, end_s, text
ConceptOut        id, name, source, implicit, start_s?, end_s?
LectureDetailOut  LectureOut + segments[] + concepts[]
LectureProgressOut lecture_id, status, stage, progress_pct, detail, elapsed_s, updated_at
CourseSummaryOut  course_id, total_lectures, ready_lectures, total_concepts,
                  has_graph, node_count, edge_count
GraphEdgeOut      source, target, confidence, source_method="classifier", evidence?
CourseGraphOut    course_id, nodes[], edges[], node_count, edge_count, is_dag, topological_order[]
CourseBuildOut    status, course_id
ClipOut           id, concept_name, start_s, end_s, path, ok, error?
ClipBatchOut      lecture_id, status, clips[]
QuizQuestionOut   id, concept, question, options[]
QuizOut           quiz_id, course_id, student_id, questions[]
QuizSubmitOut     quiz_id, student_id, score, total, remediation[], feedback[]
WatchItemOut      concept, failed, clip?
QuestionFeedback  question_id, concept, correct, selected?, answer?,
                  explanation?, rationale?
/stats dict       course_id, heatmap[{concept, wrong, attempts, rate}],
                  divergence[{concept, taught_idx?, learned_idx?, gap}],
                  taught_order[], learned_order[]
```

## 4. Caching contract (frontend side — both engines honor this)

- **Never cache** `/lectures/{id}/progress`, uploads, or writes.
- **Cache with TTL + explicit invalidation**: lists 60 s, detail/stats/graph/
  clips 300 s.
- **Invalidate on every mutation** that can change a course or lecture
  (upload, delete, concepts ready, graph ready, clips ready, rerun): clear the
  course list, lecture list, and the affected course's scoped keys.
- `401` must never be satisfied from cache and must never be silent.
- React engine: implement the same rules with React Query (TTL + `invalidateQueries`
  by prefix) to keep cross-engine behavior identical.

## 5. Known backend limitations (documented so frontends render them honestly)

1. Jobs are `BackgroundTasks`, progress in RAM, keyed by `lecture_id` — one slot
   per lecture; a restart orphans jobs (Engine-2 precondition R1 fixes).
2. Duplicate uploads are not deduped; every `POST /lectures` creates a new row.
3. `POST /quizzes` is destructive and blocking (see §2) — concurrent generation
   races question ids (Engine-2 precondition R4).
4. Concurrent graph builds for one course are last-committer-wins (self-healing
   via cache signature), so transiently a shorter graph may be served.
5. `POST /courses/{id}/graph` without `lecture_id` publishes no progress. The
   Streamlit engine always passes `lecture_id`.