# Decisions Log

This file exists for one reason: to keep the rest of the documentation
grounded in what was actually decided, rather than in anything proposed
and never confirmed. Every other doc in this repo should trace back to a
line in this file. When in doubt, this file wins.

## Confirmed

- **Lecture Structure pass replaces chunk-atomic extraction (2026-09-15).** One
  consolidated LLM read of the transcript (sliding windows + rolling context)
  emits passages (span/title/concepts taught/evidence text), per-concept
  teach-spans, and transcript-grounded prerequisite links with verbatim evidence.
  Supersedes Stage 2b `refine_timeline.py` (retained only as a fallback path) and
  re-grounds Stages 2/5/6 in the structure. Full design: `plan/LECTURE_STRUCTURE.md`.
- **Prerequisite signal becomes transcript-first, classifier demoted to
  fallback (2026-09-15).** Edges from the structure pass's `links` are primary
  (confidence 0.9); the LectureBank frozen-baseline classifier (F1 0.569) fills
  only pairs the transcript never grounds (notably cross-lecture) and backs the
  name-embedding dedup. Complements the earlier "frozen baseline locked" Phase 3
  decision rather than replacing the work.

- **Topic is finalized:** Lecture Comprehension Gap Detector (LecGap). No
  further topic exploration or rebuilds.
- **Team size:** 4 people, including Ayush. Reliability of full
  participation from all members is uncertain; Ayush is prepared to
  execute solo if needed. This is treated as a live risk, not resolved —
  see `docs/TEAM.md`.
- **Core reframe:** replace a hand-curated prerequisite JSON with an
  automatically learned, evaluated prerequisite graph. This is the
  project's central technical claim.
- **Evaluation benchmark:** LectureBank 1.0 (208 labeled pairs, 5
  domains), not LectureBank2.0, because LectureBank2.0 is
  predominantly NLP-sourced and a weaker match for this project's ML/DL
  test lectures.
- **Visual-track extension:** CLIP + OCR added to Stage 2, to catch
  concepts shown on screen but never spoken aloud. Chosen over training a
  CNN from scratch, since no labeled dataset of "lecture visual concepts"
  exists and CLIP/OCR require no manual labeling.
- **Classifier training approach:** fine-tune a pretrained embedding
  model, not train a classifier from scratch — LectureBank's labeled data
  is too small to train reliably from zero.
- **Refinement-loop validation approach:** a controlled synthetic-student
  recovery experiment (hidden ground-truth graph + LLM-persona synthetic
  students that reason through answers), not a real classroom pilot.
  Chosen specifically because reliably recruiting real volunteer test
  users was judged unrealistic for this team. Full detail in
  `docs/EVALUATION.md`.
- **Roadmap structure:** phases organized by complexity and estimated
  timeframe (weekly/monthly, continuous), not split by semester
  boundary — because semester deadlines are administrative, not
  technical, and are frequently not actually followed in practice.
- **Process:** markdown documentation is written and agreed *before*
  implementation begins, in a decoupled (not monolithic-script)
  architecture.
- **Environment management:** conda, in practice. The dev machine runs a
  conda env named `lecgap` (`D:\Anaconda3\envs\lecgap`, Python 3.10.20),
  and every documented command in the README targets it. Locked after
  working exclusively with conda through Phase 1 — no reason to revisit
  unless a teammate's machine workflow requires it.
- **Repo location:** this folder, `lecture-comprehension-gap-detector`,
  on the Desktop.
- **Backend/frontend split (accepted as starting point, open to
  revision):** FastAPI backend + Streamlit frontend, SQLite behind the
  API. Explicitly not treated as final — Ayush flagged he may want to
  upgrade the frontend (e.g. to a dedicated framework instead of
  Streamlit) later if the need shows up. Revisit before Phase 6/8 UI
  work begins if that's still under consideration.
- **Roadmap phases and estimates (accepted as starting point, open to
  revision):** the phase table in `docs/ROADMAP.md`, accepted as a
  working plan rather than challenged line by line.
- **Frontend split into two Streamlit entrypoints (2026-09-24).** The single
  `frontend/app.py` (two tabs) is replaced by `frontend/student_app.py` +
  `frontend/faculty_app.py` sharing a pure-Python API client + cache layer
  (`frontend/client.py`, `frontend/state.py`, `frontend/components.py`).
  `frontend/render.py` stays. Full design: `plan/FRONTEND_ARCHITECTURE.md`.
- **Two-tier frontend cache (2026-09-24).** Tier-1 = `client.CacheStore`
  (pure-Python TTL dict, module singleton shared across sessions in a process),
  60 s lists / 300 s heavy reads, invalidated explicitly on every mutation.
  Tier-2 = `state.py` over `st.session_state` for per-user UI state (active quiz,
  loaded stats/DAG, job monitor list). This fixes audit defects: quiz/stats lost
  on job-poll reruns, stale list after course delete, misleading "no courses"
  when the backend 401s.
- **Multi-job monitor (2026-09-24).** The single `lecgap_job` session binding is
  replaced by a job *list* so starting a second job never silently drops the
  first. Backend progress stays `lecture_id`-keyed (no job registry this phase) —
  cross-user progress transparency is improved by seeding the monitor from
  in-flight lectures, with the concurrent-sharing limitation documented.
- **Stay Streamlit now; React roadmap documented (2026-09-24).** No framework
  switch this phase. The React engine (`plan/FRONTEND_REACT_ROADMAP.md`) is a
  leaf-replacement over the same locked HTTP contract
  (`plan/FRONTEND_API_CONTRACT.md`), gated on the backend job registry + quiz
  idempotency and run only when the roadmap's trigger condition fires. Overrides
  the still-open "dedicated framework" note below by making the swap a
  documented, cheap path instead of an open question.
- **Media endpoint added (2026-09-24).** New `GET /media/clips/{lecture_id}/{filename}`
  (Range-capable) is the canonical playback URL; payloads keep filesystem paths
  in v1 and the frontend maps them at the edge. Fixes the broken `st.video`
  remediation playback without breaking the contract.
- **Student-dashboard quota transparency + course-key consistency (2026-09-24).**
  First focused iteration (plan §10). Backend: `GET /usage` (guarded, like
  `/llm/backends`) + `backend/api/usage.py` capturing Groq rate-limit headers on
  every LLM/Whisper call, split per service (`groq.chat` / `groq.whisper`);
  `LectureProgressOut.duration_s` published at the ffprobe probing stage gives a
  **live-accurate** per-lecture request estimate. Frontend (student dashboard
  only): per-service usage row + "this lecture ≈ N requests ≈ X%" once probed;
  canonical course KEY `^[A-Z][A-Z0-9-]{0,127}$` via
  `client.normalize_course_id` (normalize + **soft-warn**, non-breaking);
  duplicate-upload (course, filename) soft-warn. Faculty status and the course
  snapshot stay queued.
- **Non-blocking two-step upload (2026-09-25, shipped).** `POST /lectures`
  without a file creates the row fast; `PUT /lectures/{id}/media` streams the
  body with live `uploading` progress (Content-Length required, 409 unless
  status `uploaded`, 413 cap, abort-safe), then schedules transcription.
  Frontend uploads from memory in 1 MiB slices inside a background thread with a
  Cancel button (`.streamlit/config.toml` maxUploadSize=2048). Fixes the
  frozen-button report; single-shot multipart POST retained for API compat.
  `plan/FRONTEND_ARCHITECTURE.md` §11.
- **Course snapshot (B1, 2026-09-25, shipped).** New derived `GET /courses/{id}/snapshot`
  (grouped counts + `in_flight` from `uploaded|transcribing` lecture rows enriched
  with the live progress stage; never 404). Frontend polls it at a 5s TTL on both
  dashboards (readiness strip, sidebar counts now live), and monitor seeding now
  comes from `snapshot.in_flight` — **transcribing only**, fixing finding A1 (a
  stuck `uploaded` row renders as an "awaiting media" hint, never a spinning
  card). Faculty additionally gained the usage row (B2 usage half). Findings
  audit recorded in `plan/FRONTEND_ARCHITECTURE.md` §12.

## Proposed — not yet confirmed

*(None pending. The 2026-09-15 lecture-structure decisions were confirmed
 and moved to the Confirmed list above.)*

## How to use this file

## How to use this file

Before adding a new architectural or methodological detail anywhere in
this repo, check: is it in the "Confirmed" list? If not, either get it
confirmed and move it up, or leave it clearly marked as proposed. Nothing
should quietly become "the plan" just because it was written down once.
