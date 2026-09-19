# SYSTEM_EVAL: Comprehensive Technical Evaluation, Code Audit, and Architectural Blueprint

> **Status:** Re-audited 2026-09-18 using the `agent-skills` review pack (code-reviewer, security-auditor, test-engineer, web-performance-auditor) in parallel fan-out. Findings are cross-referenced, severity-tagged, and tracked to resolution below. Previous audit content was superseded because the codebase moved from a single `backend/api/routes.py` to `backend/api/routes/{courses,lectures,quizzes}.py` and the pipeline has since changed (silence-snap chunking, clip re-encoding, LLM reasoning gating, parallel MCQ generation).
>
> **Update 2026-09-19:** reconciled the fix register with the tree (`209 passed`). P9's M4 (`/courses` N+1 → grouped aggregates, `c143daa`) and the entire P12 test backlog (`53d8ae8`) are closed. H4's cached classifier + M8's vectorized cosine actually landed earlier (`edc85cc`, `ae0c3b2`) but were still marked deferred here — corrected below. Still open: H3 (dedicated worker process), H6 (quiz-prep N+1 remainder), M5, M1, L10.

---

## 1. Executive Summary & Problem Statement

The **Lecture Comprehension Gap Detector (`LecGap`)** converts passive lecture watching into an active, diagnostic learning loop: ingest lecture media → transcribe → extract concepts → build a prerequisite DAG → quiz students → remediate comprehension gaps with targeted video clips.

The 2026-09-18 parallel audit found the system in a **strong structural state** (no SQLi, no `shell=True`, no committed secrets, hermetic offline test suite, WAL+single-commit-per-stage DB discipline) but with **one critical live bug, several latent correctness bugs, and a class of integrity/security gaps** that must be resolved before the system can be trusted beyond the demo path.

The three most important themes:

1. **A shipped feature is a silent no-op.** The silence-aware chunk snapping added on 2026-09-18 (`d78657f`) never executes because `backend/pipeline/transcribe.py` calls `re.findall` without importing `re`; the `NameError` is swallowed by a bare `except Exception: pass`. Every call path reports success.
2. **Quiz integrity is defeated by the answer key leaking in the API payload.** `QuizQuestionOut` returns the three distractor columns *and* the shuffled options (which are exactly `{answer} ∪ distractors`), so a client recovers ground truth by elimination — contradicting the documented contract (`mcq_gen.py:18`, `schemas.py:161`).
3. **The audit-shown fixes of today are mostly untested.** Seven behavior commits shipped on 2026-09-18; six of them changed no test file. The silence-snap path, LLM-reasoning branch, remediation endpoint, worker error paths, synthetic-student de-leak, and parallel-MCQ exception behavior all lack regression coverage.

---

## 2. End-to-End Lecture Lifecycle: Current Code Walkthrough

Updated artifact layout (the old single `backend/api/routes.py` no longer exists):

```
[User Media Upload] (backend/api/routes/lectures.py)
       │  streaming write (1 MiB chunks), cap LECGAP_MAX_UPLOAD_MB (0 = unlimited)
       ▼  BackgroundTask
[Stage 1: Transcription] (backend/pipeline/transcribe.py)
       ├── _downmix_to_flac → mono 16 kHz FLAC
       ├── _split_flac → fixed chunk_s windows (snap_silence/LECGAP_SNAP_SILENCE=1 intended to align
       │     boundaries to ffmpeg silencedetect pauses — currently a NO-OP, see Finding C1)
       └── local Whisper or Groq Whisper (≈10× real-time, live-measured)
       ▼  persist TranscriptSegment rows
[Stage 2: Concept extraction] (backend/pipeline/extract_concepts.py)
       ├── chunks → LLM names explicit + implicit concepts
       ├── MiniLM dedup (single batched encode, build_graph.py)
       └── refine_timeline.py pins [start_s, end_s] (fallback stride-samples wide spans)
       ▼  persist Concept rows
[Stages 3 & 4: Prerequisite classification + DAG] 
       │  classify_prerequisites.py → candidate pairs (temporal + cosine) → LogisticRegression
       │    head over MiniLM name embeddings; LECGAP_LLM_REASONING=1 adds per-edge LLM check
       ▼  build_graph.py → NetworkX DiGraph → resolve_cycles (drops lowest-confidence edge)
[Stage 5: Clip segmentation] (backend/pipeline/segment_clips.py)
       └── spans ≤ LECGAP_CLIP_REENCODE_THRESHOLD_S (120s) re-encode libx264 (frame-accurate);
             long spans stream-copy; per-clip failure isolation
[Stage 6: Quiz generation] (backend/api/routes/quizzes.py)
       ├── ThreadPoolExecutor (min(6, n)) generates per-concept MCQs (bounded, order-preserving)
       ├── LLM prompt from passage/local_context; fallback make_mcq (evidence sentence + filtered distractors)
       └── llm_cache (hash-keyed, SQLite) makes repeats free
[Stage 7: Submission + remediation] (backend/api/routes/quizzes.py)
       ├── server-side grading vs stored answer; attempt increments
       └── graph transitive closure → prerequisite clips in topological order (backend/pipeline/quiz.py)
```

---

## 3. Findings Register (severity-ordered)

Severity legend — **Critical** (blocks release / data loss / silent failure), **High** (must fix before relying on), **Medium** (fix in sprint), **Low** (defense-in-depth / best practice). Each finding lists auditors: `CR` = code review, `SE` = security, `TE` = test coverage, `PF` = performance.

### 3.1 Critical

#### C1. Silence-aware snapshotting is a silent no-op — `transcribe.py` missing `import re`
- **Location:** `backend/pipeline/transcribe.py:115-139, 151-165`
- **Auditors:** CR (confirmed), TE (confirmed), independently verified.
- **Description:** `_detect_silence_offset` calls `re.findall(...)` at line 133, but the module imports only `os, shutil, subprocess, tempfile, time`. The `NameError` is caught by the bare `except Exception: pass` at line 137, so the function unconditionally returns `target_s`.
- **Impact:** The `d78657f` feature does nothing, yet every call path reports success — words still get sliced mid-utterance, and no error alerts the operator. No test exercises snapping, so the suite stays green.
- **Fix:** Add `import re`; add unit tests that pin a snapped split point and the clamp behavior. **(status: fixed)** See fix record below.

#### C2. Snapping breaks timestamp offsets — latent until C1 is fixed
- **Location:** `backend/pipeline/transcribe.py:296-297`
- **Auditors:** CR, TE.
- **Description:** `offsets = [float(i * chunk_s) for i in range(len(chunks))]` assumes uniform chunk boundaries. Snapping moves boundaries by up to ±5s (clamped to `+30..+chunk_s+5`), so every downstream segment's `start/end` drifts against the audio once snapping works.
- **Impact:** Misaligned transcript → wrong concept spans → wrong clip windows.
- **Fix:** Return `(path, actual_start_offset)` pairs from `_split_flac` and build offsets from the cumulative split points. **(status: fixed)**

#### C3. Quiz answer key is recoverable client-side
- **Location:** `backend/api/schemas.py:124-131`, `backend/api/workers.py:597-613`
- **Auditors:** CR (R3), SE (C2).
- **Description:** `QuizQuestionOut` serializes `distractor_a/b/c` columns alongside the shuffled `options` where `options == {answer} ∪ {distractors}`. Deterministic recovery: answer = the option not in the three distractor fields. The documented contract (answer/explanation never leaked by GET /quizzes) is defeated. `tests/test_api.py:500-504` only asserts `answer`/`explanation` keys are absent — it misses the distractor columns.
- **Impact:** Quiz integrity zero; students can trivially score 100% and pollute remediation/heatmap signals.
- **Fix:** Remove `distractor_a/b/c` from the response schema and from `_question_out`. Frontend needs only `id/concept/question/options` (`frontend/app.py:266-274`). **(status: fixed)**

#### C4. No authentication; full IDOR on every endpoint
- **Location:** `backend/main.py:21-28`, all route modules
- **Auditors:** SE (C1).
- **Description:** No auth dependency, no middleware, no CORS restriction anywhere. Every endpoint is keyed on caller-supplied `course_id`/`lecture_id`/`student_id`: enumerate all courses/lectures, read any student's remediation, fabricate `QuizResponse` rows for any student, mass-delete courses, and trigger unbounded LLM spend.
- **Impact:** Complete confidentiality/integrity/availability loss once the API is bound beyond `127.0.0.1`.
- **Fix (deferred — local tool by design, README binds localhost):** add auth at router level, derive `student_id` from the session, validate resource ownership; at minimum document the trust boundary. Not blocking for the documented single-user local deployment.

### 3.2 High

#### H1. Worker failure paths leave `Lecture.status == "ready"`
- **Location:** `backend/api/workers.py:292-307` (`_extract_concepts_worker`), `:360-371` (`_cut_clips_worker`)
- **Auditors:** CR, TE.
- **Description:** Failure handlers write `lecture.error` but never set `lecture.status = "error"` (unlike `_process_lecture` at `:137`). `_progress_finish` pops the in-memory entry, so the next frontend poll hits the DB fallback (`workers.py:89-92`), sees "ready", and reports success — masking the failure.
- **Fix:** Set `lecture.status = "error"` in both except blocks; add end-to-end worker error tests. **(status: fixed)**

#### H2. Hallucinated spoken links create phantom graph nodes
- **Location:** `backend/api/workers.py:491-505`, `backend/pipeline/build_graph.py:162-165`
- **Auditors:** CR.
- **Description:** `graph.add_edge(a, b, ...)` auto-creates endpoints that aren't extracted concepts. A `LectureLink` whose `source_name`/`target_name` was never extracted (LLM hallucination/name-variant/cross-lecture reference) produces a `GraphNode` with no `Concept` row, then flows into topo order and remediation.
- **Fix:** Only add transcript edges whose resolved endpoints exist in the extracted `names` set (or resolve through dedup and skip unknowns). **(status: fixed)**

#### H3. Pipeline runs on the shared request threadpool
- **Location:** `backend/api/workers.py:106,173,316,400`; scheduled via `BackgroundTasks`
- **Auditors:** PF (High #1).
- **Description:** Whisper, torch/MiniLM, per-window/per-concept LLM calls, and ffmpeg run as sync callables in the same anyio threadpool serving HTTP. The cold sentence-transformers import (~35-60s) happens inside a request thread.
- **Impact:** Under multi-lecture runs, `/health`, `/courses`, and 1s `/progress` polling stall; CPU thrash from concurrent whisper jobs.
- **Fix (structural, deferred):** move pipeline jobs to a dedicated worker process/queue with bounded concurrency (1-2 jobs).

#### H4. Whole-course graph rebuild after every lecture
- **Location:** `backend/api/workers.py:288-307, 410-558`; `classify_prerequisites.py:296-342, 50-102`; `build_graph.py:93-135`
- **Auditors:** PF (High #2).
- **Description:** Each lecture rebuild re-fits the classifier head on LectureBank, regenerates O(n²) candidate pairs via per-pair pure-Python `_cosine` (fresh numpy allocations per comparison), and constructs a fresh encoder. The encoder is only shared within a single rebuild.
- **Fix:** lazily cache encoder + fitted classifier at module level; vectorize similarity as one normalized matmul; debounce/coalesce rebuilds per course. **(status: fixed, except debounce/coalesce)** — `_get_shared_classifier` (`workers.py:43-66`) and `_fitted_classifier` (`classify_prerequisites.py:276-357`) now hold a process-wide encoder + one fitted LectureBank head reused by every rebuild; candidate-pair cosine is a single batched L2-normalized matmul (`classify_prerequisites.py:81-100`). See `edc85cc`, `ae0c3b2`. Debounce/coalesce of concurrent rebuilds per course remains open.

#### H5. Quiz generation blocks the request and has a cache-fill race
- **Location:** `backend/api/routes/quizzes.py:98-124`; `backend/pipeline/llm.py:60-94, 178-225`
- **Auditors:** PF (High #3).
- **Description:** `POST /quizzes` is a synchronous request (no background job). Six threads each open a session, MISS, call Groq, INSERT/commit. Two threads missing the same key call the API twice, then both insert → PK `IntegrityError` surfaced in `_make_one`'s `except Exception` → the LLM-written MCQ is silently dropped for the evidence fallback while quota was double-billed.
- **Fix (fixed):** single-flight/lock per cache key **and** `INSERT OR IGNORE` (see P5). Moving quiz generation to a background worker remains a structural follow-up.

#### H6. Quiz prep is N+1 over the whole course transcript
- **Location:** `backend/api/routes/quizzes.py:60-66, 68, 75-84, 100`; `workers.py:561-574`; `quiz.py:139-172`; `mcq_gen.py:126-160`
- **Auditors:** PF (High #4).
- **Description:** For each of ~50-200 concepts, the route rescans the course-wide segment list (≥2-3×) and loads every course segment into RAM; passage rows fetched one-by-one.
- **Fix (deferred):** batch passage load (single `IN`), precompute per-concept evidence into `passages`, build a name→sentence index in one pass.

### 3.3 Medium

#### M1. LLM output is trusted as ground truth (prompt-injection surface)
- **Location:** `backend/pipeline/passages.py:404-416`, `refine_timeline.py:135-140`, `mcq_gen.py:266`, `extract_concepts.py:114-119`, `workers.py:515-523`, `refine.py:201-206`
- **Auditors:** SE (H3), CR (Optional), TE.
- **Description:** Uploaded-lecture transcript text is interpolated verbatim into LLM prompts with no "untrusted data" delimiter or ignore-instructions guard. Attacker-influenced audio can steer concept names/times/edges; the `llm_reasoning_check` verdict hard-gates edges when `LECGAP_LLM_REASONING=1`, and synthetic-student lines starting not-`PASS` count as `FAIL`.
- **Fix (deferred):** delimit transcript data, treat LLM verdicts as confidence-weighted, not binary gates.

#### M2. Internal exception text exposed to clients
- **Location:** `backend/api/workers.py:131-141, 221-230, 295-307, 92`; `schemas.py:27`; `transcribe.py:111, 178`; `llm.py:139`
- **Auditors:** SE (M1).
- **Description:** `type(exc).__name__: {exc}` strings (incl. ffmpeg stderr, temp paths, Groq internals) are persisted to `lecture.error` and returned to callers; no custom exception handler in `main.py`.
- **Fix (fixed):** log full detail server-side; return generic client messages; add `@app.exception_handler` (see P7).

#### M3. Client-trusted grading on legacy questions + cross-course pollution on submit
- **Location:** `backend/api/routes/quizzes.py:179-184, 206-227`; `schemas.py:141-146`
- **Auditors:** SE (M2, M3), TE (High #4).
- **Description:** `QuizAnswerIn.correct` is client-supplied and trusted when a question row has NULL `answer`; responses are recorded under caller-supplied `course_id`/`student_id` with no consistency check against the question's real course.
- **Fix (fixed):** remove `correct` from the request schema; require `quest.course_id == payload.course_id` (see P6).

#### M4. `/courses` is N+1 and re-fetched on every Streamlit rerun
- **Location:** `backend/api/routes/courses.py:39-66`; `frontend/app.py:86-92, 149`
- **Auditors:** PF (Medium #5).
- **Fix:** single aggregated GROUP BY query; `@st.cache_data` on the frontend. **(status: fixed)** — `/courses` computes lecture/concept/node/edge counts via four grouped queries (`courses.py:36-78`, `c143daa`), killing the per-course round-trip loop; the frontend now memoizes the summaries through `_course_summaries` (`@st.cache_data(ttl=60)`) and the sidebar "Refresh course list" button calls `.clear()` so uploads/deletes still surface (`app.py:86-98,153-161`). Frontend regression tests in `test_frontend_app.py` (cache passthrough stub + clear wiring).

#### M5. Unpaginated endpoints + stats recompute full tables and graphs
- **Location:** `lectures.py:100-114`; `courses.py:146-203`; `quizzes.py:169-227, 244-250, 308-313`
- **Auditors:** PF (Medium #6, #8); TE (High #3).
- **Fix (deferred):** paginate lists; SQL aggregates for heatmap/divergence; brief graph-dict cache keyed on rebuild version.

#### M6. SQLite writer contention around `llm_cache` and parallel writers
- **Location:** `db.py:44-62`; `llm.py:60-94`; `workers.py:282, 552`
- **Auditors:** PF (Medium #7).
- **Fix (bundled with H5):** reuse a process-wide writer with short transactions + idempotent inserts.

#### M7. Serial sequential LLM loops where bounded concurrency applies
- **Location:** `extract_concepts.py:113-130`; `refine_timeline.py:178-191`; `workers.py:510-524`; `transcribe.py:302-310`
- **Auditors:** PF (Medium #8).
- **Fix (deferred):** small ThreadPoolExecutor caps (2-4) for independent LLM sub-calls.

#### M8. O(n²) pure-Python cosine reintroduces allocation churn
- **Location:** `build_graph.py:114-135, 253-256`; `classify_prerequisites.py:91-100`
- **Auditors:** PF (Medium #9).
- **Fix:** single L2-normalized matrix + one `matmul`. **(status: fixed)** — `_fitted_classifier`-path candidate scoring is `sim = mat_n @ mat_n.T` and `_pair_features` assembles via vector indexing (`classify_prerequisites.py:81-128`). `build_graph._cosine` remains only for the small per-node dedup scan against the shared `_vec_cache` (`build_graph.py:123-130, 253-256`).

### 3.4 Low

| ID | Location | Finding | Auditor |
|----|----------|---------|---------|
| L1 | `quizzes.py:126-128`, `db.py` | Regenerating a quiz leaves stale `QuizResponse` rows (FKs never enforced); course_stats/remediation accumulate dead answers | CR |
| L2 | `classify_prerequisites.py:202-204` | Undersample branch raises when `neg_idx` smaller than requested; zero-positive fit on empty matrix | CR |
| L3 | `workers.py:488,502` | Reaches into classifier privates (`clf._encoder`) | CR |
| L4 | `lectures.py:82-91` | Non-atomic upload: partial file + committed row on mid-write failure | SE (H1), CR |
| L5 | `workers.py:517-523` | LLM-reasoning parse failure keeps edge on classifier confidence (consider veto) | CR |
| L6 | `transcribe.py:162` | `start + 30.0` clamp assumes `chunk_s ≥ 30` | CR |
| L7 | `transcribe.py:56-62` | `_get_model` not thread-safe → double model load on concurrent first use | PF |
| L8 | `segment_clips.py:213-220` | fixed worker count can oversubscribe when other stages run | PF |
| L9 | `frontend/app.py:103-134,277` | 1s unbounded progress polling, hard-coded `latency_s: 2.0` | PF, CR |
| L10 | `environment.yml:7-32` | Unpinned deps; opencv CVE-2025-53644 / CVE-2023-4863, transformers CVE-2024-3568 + 5.3.0 RCE family apply depending on resolved versions | SE |
| L11 | `refine.py:181` | `generate_synthetic_students` unbounded on `n` | SE |
| L12 | `segment_clips.py:67-74` | NaN/inf flows as `-ss nan` (fails closed, but reject non-finite explicitly) | SE |
| L13 | `frontend/app.py:305-306` | `st.video` plays server-local paths | CR |

### 3.5 Test-coverage findings (TE)

- Seven behavior commits on 2026-09-18; **six shipped without test changes** (`d78657f`, `8581cc0`, `8b939d8`, `24fde01`, `0e401df`, `a7bfd86`). Only `50959af` (segment_clips) updated a test file.
- **Worst gaps (now fixed with their fixes):** silence-snap path; LLM-reasoning branch integration; worker error paths; quiz answer-key leak.
- Remaining gaps (now closed with the audit fixes): `get_remediation` endpoint; legacy probe grading + attempt increments; `create_quiz` 404-no-concepts; worker error paths; quiz answer-key leak.
- Remaining gaps (now also closed): `courses.py` fallback branches (`test_course_stats_falls_back_to_taught_order_without_graph`); `_rebuild_course_graph` short-circuits (`test_rebuild_graph_shortcircuits_without_concepts`); `purge_course` completeness (`test_delete_course_purges_everything` now asserts TranscriptSegment/Passage/LectureLink/Clip/GraphEdge); `fine_tune.py` training/export path (`test_fine_tune.py` export/load/predict + `_pair_text`); `frontend/app.py` (new `test_frontend_app.py` hermetic stubs for `_get/_post/_delete`, `_wrap_progress`, `_wait_progress`, `_course_options`). All landed in `53d8ae8` (+`6dd749a`).
- **Quality issues (open):** `test_api.py:55` globally mocks `quizzes.generate_mcq` → `pool.map` exceptions can't surface; `test_quiz_refine.py:59-62` vacuous; `test_transcribe.py:286-297` asserts ffmpeg arg ordering (brittle); `test_llm.py:19` module-level env mutation; `test_classify_prerequisites.py:43` vectors vary with `PYTHONHASHSEED`; three stray fixture tests under `agent-skills/` still collected by a bare `pytest` from repo root (safe when scoping to `pytest tests` — dir now gitignored via `ab30c0c`).

### 3.6 Positive observations (all auditors)

- **No SQL injection** — all data access is SQLAlchemy bound parameters; only raw SQL is additive DDL (`db.py:366-375`).
- **Subprocess safety is solid** — argv lists only, no `shell=True`; `-ss/-t` values float-coerced with `:.3f`; commands time out; concept names sanitized before filenames (`segment_clips.py:58-64`).
- **Secrets clean** — `.env` gitignored, no `gsk_` token in history, key only read via `os.getenv`, never logged.
- **DB discipline** — WAL + busy_timeout + `synchronous=NORMAL`; one commit per stage; `expire_on_commit=False`/`autoflush=False`.
- **Hermetic tests** — Whisper/Groq/ffmpeg fully monkeypatched; single in-memory StaticPool in `test_api.py`; CI experience offline.
- **Graceful LLM degradation** — strict parsing with clamps/bounds; fallback-to-evidence never raises to client; reset-header-aware backoff with sleep cap.
- **Per-clip failure isolation** in `segment_clips.py`; re-encode-vs-stream-copy threshold now frame-accurate for concept clips.

---

## 4. Fix Records (work started by priority)

Each entry records status; the "Regressions covered" column links to the test that pins the fix.

| # | Finding | Status | Commit / notes |
|---|---------|--------|----------------|
| P1 | C1 + C2 — `import re` + real snapped offsets + tests | **fixed** | See below |
| P2 | C3 — quiz answer-key leak | **fixed** | Remove distractor fields from schema + `_question_out` |
| P3 | H1 — worker error status | **fixed** | `status="error"` in both failure handlers |
| P4 | H2 — phantom graph nodes | **fixed** | Gate transcript edges on extracted concept membership |
| P5 | H5/M6 — llm_cache fill race | **fixed** | single-flight + `INSERT OR IGNORE` |
| P6 | M3 — grading consistency | **fixed** | drop client `correct`; course consistency check |
| P7 | M2 — error text sanitization | **fixed** | generic client messages + exception handler |
| P8 | H3/H4 — worker process + cached classifier | **fixed (H4)** / H3 open | cached classifier + vectorized cosine landed (`edc85cc`, `ae0c3b2`); dedicated worker process still structural |
| P9 | H6/M4/M5/M8 — N+1 & single-pass prep | **in progress** | M4 + M8 fixed (see below); H6 quiz-prep N+1 and M5 pagination/stats still open |
| P10 | M1 — prompt-injection boundaries | pending | LLM-verdict weighting + untrusted-data delimiters |
| P11 | L10 — dependency pinning + CVE scan | pending | conda-lock + pin hub model IDs |
| P12 | Test backlog (TE recommended list) | **closed** | all listed TE gaps covered; quality issues list remains (see §3.5) |

### P1 detail — silence-snap correctness

- Added `import re` to `backend/pipeline/transcribe.py`.
- `_split_flac` now returns `(path, start_offset)` so callers build offsets from the real cumulative split points (`split_point`), not `i * chunk_s`.
- Added unit tests: `_detect_silence_offset` returns `start_search + best` on a `silence_start` hit, `target_s` on no markers, `target_s` on ffmpeg error; snapping clamps to `[start+30, start+chunk_s+5]`; the trailing-remainder guard (> 15 s) suppresses snapping on the final chunk.

### P2 detail — quiz answer-key leak

- Removed `distractor_a/b/c` from `QuizQuestionOut` (`backend/api/schemas.py`).
- `_question_out` (`backend/api/workers.py`) no longer returns the distractor columns.
- Frontend unaffected (uses only `id/question/concept/options`).
- Test pins: response contains shuffled `options` and no `distractor_*`/`answer`/`explanation` keys.

### P3 detail — worker error status

- `_extract_concepts_worker` and `_cut_clips_worker` failure paths now set `lecture.status = "error"` before persisting `lecture.error`.
- Test pins: raising pipeline stage ⇒ `status=="error"`, `error` text set, progress entry pruned.

### P4 detail — phantom graph nodes

- Transcript `LectureLink` edges are only inserted when both resolved endpoints are in the extracted concept name set (post-dedup); unknown-name links are skipped (logged), preventing orphan `GraphNode`s.

### P5 detail — llm_cache fill race

- `llm.complete` wraps the miss path in a per-key **single-flight** lock (`_KeyLockMap`, refcounted so the map stays bounded): the first thread to miss calls the backend and fills the cache; concurrent waiters re-read the cache and reuse the result — one API bill per distinct prompt, no duplicate-PK crash.
- `_cache_put` switched from `db.merge` to `sqlite_insert(...).on_conflict_do_nothing()` so a cross-process duplicate insert is a no-op.
- Test pins: 8 threads on the same fresh key ⇒ exactly 1 backend call, 7 served from cache; double `_cache_put` of one key raises no `IntegrityError`.

### P6 detail — grading consistency

- `QuizAnswerIn.correct` removed from the request schema — the client only ever reports what it *selected*; a question without a stored answer key grades as wrong (no client flag is trusted, so remediation/heatmap signals stay honest).
- `submit_quiz` now rejects answers whose `question.course_id != payload.course_id` (HTTP 400) — no cross-course `QuizResponse` pollution.
- Test pins: cross-course submit ⇒ 400; legacy no-key question with client-claimed `correct=True` grades wrong, score 0.

### P7 detail — error text sanitization

- `workers._client_error_message` replaces `f"{type(exc).__name__}: {exc}"` in all four pipeline workers (transcription / extraction / graph rebuild / clip cutting): full detail is logged server-side, `lecture.error` carries a generic "`<Stage>` failed — see server logs for details." message.
- `main.py` adds a catch-all `@app.exception_handler(Exception)` returning a generic 500 (no internals echoed).
- Test pins: failing transcribe/extract/clips workers leave `status=="error"` with no ffmpeg paths / temp dirs / Groq tokens in the client-visible message; progress endpoint reflects the error.

### P8 detail — cached classifier & vectorized cosine

- `workers._get_shared_classifier` (`edc85cc` + `ae0c3b2`): one MiniLM encoder + one LectureBank-fitted logistic head live for the process lifetime and are reused by every course-graph rebuild — previously each rebuild re-loaded the encoder and re-fit the head on the full LectureBank.
- `classify_prerequisites._fitted_classifier` + `_load_lecturebank` memo (`edc85cc`): fit is cached keyed on `(id(lib), id(encoder))` with strong-ref pinning so an `id()` cannot be recycled; lecturebank CSVs are read once per process.
- Candidate-pair cosine is a single L2-normalized `mat_n @ mat_n.T` (M8) instead of O(n²) fresh numpy allocations.
- Test pins: `test_classify_course_pairs_reuses_fitted_classifier` (identical lib+encoder ⇒ 1 fit total; fresh lib objects ⇒ fresh fits).
- **Still open (H3):** pipeline still runs on the anyio request threadpool via `BackgroundTasks` — moving to a dedicated worker process/queue with bounded concurrency remains the structural follow-up. Debounce/coalesce of rebuilds per course also open.

### P9 detail — N+1 & single-pass prep

- **M4 (fixed):** `/courses` uses four grouped `COUNT ... GROUP BY` queries (`c143daa`) instead of a per-course N+1 loop — lecture/concept/node/edge counts now come from dict lookups. Frontend `@st.cache_data` half now also fixed (`_course_summaries` + refresh clear, `test_frontend_app.py`).
- **M8 (fixed):** vectorized pair cosine — see P8 detail.
- **Still open:** H6 (quiz prep rescans/loads course-wide segments repeatedly, per-concept passage `db.get`); M5 (unpaginated lists; `course_stats` full-table heatmap/`get_course_graph` recompute per poll).

### P12 detail — TE backlog closure

- `get_remediation` endpoint: `test_get_remediation_returns_latest_sequence`, `test_get_remediation_404_without_responses`.
- Legacy probe grading + attempt increments + cross-course/legacy behavior: covered in `test_api.py` (phase6 block) incl. client `correct=True` on a no-key question grading wrong.
- `create_quiz` 404-no-concepts: `test_create_quiz_404_without_concepts`.
- Worker error paths (all four stages): `test_transcription_worker_error_is_sanitized_and_sets_status`, `test_extraction_worker_total_failure_is_sanitized`, `test_clips_worker_error_is_sanitized_and_sets_status`.
- `purge_course` completeness: `test_delete_course_purges_everything` now asserts TranscriptSegment/Passage/LectureLink/Clip/GraphEdge rows are gone alongside lectures/concepts/nodes.
- `courses.py` fallback branches: `test_course_stats_falls_back_to_taught_order_without_graph` (stats falls back to taught order when no graph).
- `fine_tune.py`: `test_pair_text_keeps_order_meaningful`, `test_export_model_saves_both_and_returns_dir`, `test_load_model_reinstates_classifier_and_tokenizer`, `test_predict_pairs_returns_one_logit_per_pair`.
- `frontend/app.py`: new hermetic `test_frontend_app.py` (streamlit/requests stubbed in `sys.modules`) covering `_get/_post/_delete` error handling, `_wrap_progress` clamp + legacy fallback, `_wait_progress` ready/error/timeout, `_course_options` summaries + lectures fallback.
- **Remaining:** the §3.5 quality issues list (none blocking).

---

## 5. Benchmarking Against NotebookLM (unchanged strategic context)

`LecGap` targets **active, diagnostic learning** (test → diagnose → remediate) with a dependency DAG, faculty confusion heatmaps, syllabus-inversion warnings, and precision remediation anchors — a moat NotebookLM (passive summarization/synthesis) does not occupy. The differentiation only materializes if the corrective fixes above land, because quiz integrity and clip accuracy are the product.

| Dimension | Google NotebookLM | LecGap target |
| :--- | :--- | :--- |
| Learning paradigm | Passive consumption | Active diagnostic loop |
| Cognitive model | Stateless Q&A | Per-node mastery state |
| Lecture processing | Flat text | Pedagogical episodes + acoustic boundary snapping |
| Assessment | Generic trivia | Misconception diagnostics |
| Remediation | Re-read summary | Precision anchors + conceptual bridges |
| Instructor insight | None | Confusion heatmaps + inversion warnings |

---

## 6. Next-Iteration Blueprint

1. **Sequential status pipeline (already largely in place)** — extraction → graph → clips chained in workers with an explicit status model; ensure every failure sets `status="error"`.
2. **Frame-accurate, pedagogically-bounded clips** — done (libx264 for ≤120 s); extend with the acoustic-boundary snapping that P1 now enables, plus padding to topic boundaries.
3. **Context-rich quiz generation** — feed full pedagogical episodes instead of 3-segment windows; enforce schema validation with Pydantic; kill the answer-key leak (P2).
4. **Transcript-aware prerequisites** — use lecture evidence for edges; treat LLM verdicts as weighted, not binary (P10).
5. **Domain-driven layering** — split `backend/pipeline` into domain / infrastructure / application services (see target layout in the archived audit).
6. **Student knowledge tracking** — record response latency + distractor selection to diagnose misconceptions, not just binary scores.