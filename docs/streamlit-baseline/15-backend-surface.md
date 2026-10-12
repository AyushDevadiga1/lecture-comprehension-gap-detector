# 15 · Backend surface the frontend depends on

**Scope note.** This file describes the backend strictly as the Streamlit
frontend sees it on `main`: which endpoints it calls, what it assumes about
responses, and where the contract is thin. Backend internals (pipeline,
registry, DB) are out of scope except where a frontend behaviour depends on
them.

## Endpoint table (verified against `backend/api/routes/` on `main`)

| Frontend call | Backend route | Notes |
|---|---|---|
| `course_summaries` | `GET /courses` | list, Tier-1 60 s |
| course delete | `DELETE /courses/{id}` | clears Tier-1, drops `nav_course` |
| `course_snapshot` | `GET /courses/{id}/snapshot` → **plain `dict`** | Tier-1 **5 s**; drives both dashboards + monitor seeding |
| `course_stats` | `GET /courses/{id}/stats` → **plain `dict`** | Tier-1 300 s |
| `course_graph` | `GET /courses/{id}/graph` | Tier-1 300 s |
| build graph | `POST /courses/{id}/graph?lecture_id=` | `lecture_id` is a **query** parameter; same path under GET is a read |
| `list_lectures` | `GET /lectures` | Tier-1 60 s |
| create row | `POST /lectures` (form fields) | step 1 of the two-step upload |
| stream media | `PUT /lectures/{id}/media?filename=&whisper_backend=` | chunked, `Content-Length` required; enqueues transcription, returns `job_id` |
| `lecture_detail` | `GET /lectures/{id}` | segments + concepts; Tier-1 300 s |
| progress | `GET /lectures/{id}/progress` | per-card live stage/% |
| `lecture_clips` / `clip_rows` | `GET /lectures/{id}/clips` | Tier-1 60 s |
| extract | `POST /lectures/{id}/concepts` | returns `job_id` |
| cut clips | `POST /lectures/{id}/clips` | returns `job_id` |
| resume | `POST /lectures/{id}/rerun` | resumable rows only |
| delete row | `DELETE /lectures/{id}` | per-row |
| quiz generate | `POST /quizzes` (blocking) | `{course_id, student_id, max_questions}`; 409 = already generating |
| quiz read | `GET /quizzes?course_id=&student_id=` | 404 = nothing generated yet |
| quiz submit | `POST /quizzes/submit` | one-shot; 404 = regenerated mid-quiz |
| remediation read | `GET /students/{id}/remediation?course_id=` | **declares `response_model=QuizSubmitOut`** (see below) |
| jobs list | `GET /jobs?course_id=&limit=` (limit 1–500) | poll fallback |
| job read | `GET /jobs/{id}` | — |
| job cancel | `POST /jobs/{id}/cancel` | — |
| **stream** | `GET /jobs/stream?interval_s=&course_id=` | SSE: `retry:` / `event: jobs` / `data: […full array…]` / `: keep-alive` |
| clip bytes | `GET /media/clips/{lecture_id}/{filename}` | byte-range capable; the only URL players use |
| quota | `GET /usage` | Tier-1 30 s |
| health | `GET /health` | — |

## Auth and transport assumptions

- `X-API-Key` header when `LECGAP_API_KEY` is set; the backend exempts
  `/health`, `/docs`, `/openapi.json`, `/redoc` and `/media/*` — **not**
  `/jobs/stream`, which is why the feed sends the key and why a bare
  `EventSource` (no header API) cannot be used.
- A change-gated **full-array** snapshot on every stream tick (never a diff);
  the client publishes only when the serialised list changed.

## Where the contract is thin (verified)

1. **`/snapshot` and `/stats` return untyped `dict`.** There is no Pydantic
   model; `tests/test_contract.py::test_every_json_route_declares_a_response_schema`
   notwithstanding, these two routes declare none, so field renames on either
   side fail at render time (`.get()` → `None` → empty panel), not in any
   test. The 5 s snapshot is the struct the whole student dashboard header
   reads — the least-typed payload is also the most-read one.
2. **`/students/{id}/remediation` declares `QuizSubmitOut`.** The remediation
   payload is typed as the submit response; anything the UI assumes about
   absent-vs-present fields (e.g. `feedback`) rests on convention, not schema.
3. **Payloads carry filesystem paths** (`Clip.path`, remediation `clip`).
   The frontend maps them to `/media/…` URLs at the render boundary and the
   contract tests forbid the reverse mapping from ever returning — but the wire
   format itself is still a path, and traversal checks live in `media_url`.
