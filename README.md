# Lecture Comprehension Gap Detector (LecGap)

## What this is

LecGap automatically learns the prerequisite structure of a course directly
from lecture recordings — instead of requiring someone to hand-type which
concept depends on which — and uses that learned structure to power two
things:

1. **Personalized remediation for students** — when a student fails a quiz
   question, the system doesn't just show them what they got wrong, it shows
   them the *correct learning order* based on what actually depends on what.
2. **Diagnostic analytics for instructors** — an aggregated view of where a
   class got confused, and where the order a concept was *taught* diverges
   from the order the data suggests it should have been *learned*.

## The core claim

Most AI study tools either skip prerequisite structure entirely or require
it to be manually curated. LecGap automatically constructs a prerequisite
concept graph from raw lecture audio and visual content, evaluates that
graph against a public benchmark, and continuously refines it using real
quiz-performance signals — closing the loop from raw video to a structured,
self-correcting curriculum model.

## Why this isn't "just another AI study app"

Tools like YouLearn, Knowt, and NotebookLM already do transcript-based quiz
generation and weak-spot review at scale. That loop is **not** the
contribution here, and this project does not claim it is — it's necessary
infrastructure, not the pitch. None of those tools do:

- An automatically learned, *evaluated*, directional prerequisite graph
  (not a generic "related topics" mind map)
- Any concept of a classroom — no multi-student aggregation, no
  instructor-facing analytics
- A mechanism that gets more accurate over time from real usage signals

See `plan/EVALUATION.md` for how the prerequisite graph and refinement loop
are actually tested, and `plan/LIMITATIONS.md` for an honest account of
where this project's claims stop.

## Project status

Implementation underway, phased by complexity (see `plan/ROADMAP.md`):

- **Phase 0 — Setup & research: done.** Environment verified; test lectures in `data/raw/`.
- **Phase 1 — Transcription pipeline: done.** Lecture upload → background Whisper
  transcription → timestamped segments persisted to SQLite, served over the API.
  Verified end-to-end against a real CampusX lecture recording.
- **Phase 2 — LLM-based concept extraction: done.** Spoken concepts extracted
  from transcript segments (chunked, cache-first LLM calls) and de-duplicated
  into a `concepts` table; served over the API.
- **Phase 3 — Prerequisite classification (core): done — frozen-encoder baseline adopted.**
  - `backend/pipeline/classify_prerequisites.py` — candidate-pair pre-filter
    (temporal + embedding similarity) and the **adopted classifier**: frozen
    MiniLM encoder + logistic head over the LectureBank pairs.
  - `scripts/evaluate_classifier.py` — nested 5-fold CV with honest
    threshold selection; **F1 0.569** on LectureBank 1.0.
  - Cross-encoder fine-tuning (MiniLM *and* bigger MPNet backbone) was
    exhaustively explored as the "better alternative" via the Kaggle GPU
    notebooks (`notebooks/kaggle_fine_tune.ipynb`,
    `notebooks/kaggle_fine_tune_mpnet.ipynb`). More epochs helped (e3→0.49,
    e5→0.53, e8→0.554) but every configuration plateaued ~F1 0.55 and **never
    beat the frozen baseline** (MiniLM e8: 0.554, MPNet e4: 0.550 vs 0.569).
    **Decision: the frozen-encoder baseline (F1 0.569) is locked in as the
    Phase 3 classifier.** Fine-tuning infra remains usable/reproducible for
    future iterations.
- **Phase 4 — Graph construction: done.** Confirmed prerequisite pairs become a
  per-course prerequisite DAG (`backend/pipeline/build_graph.py`):
  - *Deduplication:* new concept names are checked against existing graph nodes
    via embedding similarity before being added, so "Gradient Descent" and
    "GD optimization" from different lectures collapse into one node.
  - *Cycle resolution:* cycles are broken by dropping the lowest-confidence
    edge (confidence-weighted), then the graph is topologically sorted to give
    the learner order.
  - *Persistence:* nodes/edges live in `graph_nodes`/`graph_edges` SQLite tables
    per course (not a pickled file), so the Stage 7 refinement loop can swap
    edges safely.
  - Exposed via `POST /courses/{id}/graph` (background build: dedup +
    LectureBank-trained classifier scores candidate pairs) and
    `GET /courses/{id}/graph` (persisted nodes/edges + learner order).
- **Phase 5 — Clip segmentation: done.** One ffmpeg clip per concept per
  timestamp range (`backend/pipeline/segment_clips.py`, pure):
  - `cut_clip` — stream-copy `ffmpeg -ss/-to` cut for a single concept range;
    surfaces timeout/missing-binary/ffmpeg errors per clip instead of
    aborting the batch.
  - `cut_concept_clips` — batch worker writing
    `data/processed/clips/<lecture_id>/<concept>__<start>-<end>.mp4`,
    skipping concepts without timestamps.
  - Cut clips persisted in the `clips` table; API:
    `POST /lectures/{id}/clips` (background cut) + `GET /lectures/{id}/clips`.

The refinement loop (Phase 7) remains the second core claim, scheduled after
this infrastructure is stable.

## Project status — continued (Phases 6–8)

- **Phase 6 — Quiz loop & remediation ordering: done.** When a student misses a
  question, the API returns the *correct learning order* built from the
  prerequisite graph:
  - `backend/pipeline/quiz.py` — `select_remediation_sequence` (transitive
    upstream closure, ordered by learner order) + `order_quiz`.
  - DB: `quiz_questions` + `quiz_responses` tables.
  - Routes: `POST /quizzes`, `POST /quizzes/submit` (returns the remediation
    sequence for the missed concepts), `GET /students/{sid}/remediation`,
    `GET /courses/{id}/stats`.
- **Phase 7 — Refinement loop + synthetic-student validation (core claim): done.**
  The learned graph improves from *real* quiz performance signals —
  `backend/pipeline/refine.py`. `run_refinement_round` applies the plan's
  directional **co-failure** rule: if students consistently *fail* concept B
  right after also struggling with concept A, that edge A→B is reinforced;
  if they fail A but are fine with B, the edge is sunk. `generate_synthetic_students`
  realizes the plan's Claim-2 method: each synthetic student is **an LLM persona**
  (defaulting to `llm.complete`) prompted to roleplay a student taught a
  randomized subset of the hidden graph, then genuinely attempts one
  knowledge-check per concept — producing realistic, patterned errors, not
  statistical noise. `score_recovery` reports precision/recall/F1 against the
  hidden ground truth. `scripts/recovery_experiment.py` runs the controlled
  experiment (both real-LLM and an offline `--mode structural` analog):
  - **Real LLM personas** (N=8, Groq, temp 0, prompt-cached): **F1 0.571 → 0.750
    (+0.179)** — reinforces all true edges above threshold (recall ↑), though the
    spurious edge isn't fully sunk at small N (real personas are noisy).
  - **Structural analog** (N=200, deterministic): **F1 0.571 → 0.857 (+0.286)**,
    precision 0.667 → 1.000 — the spurious edge sinks below threshold and all
    true edges are reinforced, isolating the mechanism cleanly.
  This is deliberately kept **separate from real quiz data** (`plan/LIMITATIONS.md`
  #5) — it validates the mechanism, not a deployment claim.
- **Phase 8 — Faculty dashboard: done.** `GET /courses/{id}/stats` powers the
  faculty tab in `frontend/app.py`: a confusion heatmap (miss rate per
  concept per prerequisite) plus the *taught-vs-learned* divergence (where
  the order concepts were covered differs from the learner order the graph
  suggests). The frontend is a **thin HTTP client** — it never imports
  `backend/`, and the same endpoints power both the student remediation tab
  and the faculty tab.

### Frontend

```bash
streamlit run frontend/app.py
```

Student tab: upload a lecture → process → take the ordered quiz → get the
personalized remediation sequence with per-concept clip playback. Faculty
tab: heatmap of concept miss rates + taught-vs-learned divergence, both
served by the API (`GET /courses/{id}/stats`).

### Recovery experiment (Phase 7 validator)

```bash
python scripts/recovery_experiment.py   # controlled synthetic-student refinement demo
```

## Team

4 members, including Ayush. See `plan/TEAM.md` for roles and an honest
risk note on team reliability.

## Quickstart

```bash
# 1. Environment (conda; CPU-only PyTorch default so it works on any machine)
conda env create -f environment.yml
conda activate lecgap

# 2. Configure AI access (only Groq needs a key; Ollama is an optional fallback)
cp .env.example .env        # then paste your key into GROQ_API_KEY=...
# No Ollama install required — the local backend is only used if Groq is unavailable.
# Want instant transcription? set WHISPER_BACKEND=groq in .env (1-hr lecture -> ~1 min).

# 3. Start the backend
uvicorn backend.main:app --reload          # API docs at http://127.0.0.1:8000/docs

# 4. Ingest a lecture (any ffmpeg-readable audio/video)
curl -X POST http://127.0.0.1:8000/lectures \
     -F "file=@my_lecture.mp4" -F "course_id=ml"

# 5. Poll until status is "ready", then read transcript segments
curl http://127.0.0.1:8000/lectures/1
curl http://127.0.0.1:8000/health   # shows which LLM backends are usable

# 6. (Later phases) Student / faculty UI
streamlit run frontend/app.py
```

Tests and benchmarks:

```bash
# Unit tests (stubbed/monkeypatched LLM + whisper + encoder — zero API usage,
# zero model/weight download, isolated test DB). 94 tests across:
#   transcription, LLM layer, concept extraction, prerequisite classifier,
#   graph construction, clip segmentation, quiz + refinement, fine-tune helpers,
#   and API integration.
python -m pytest tests

# Regenerate the committed function inventory + dev-time module graph
python scripts/make_function_map.py        # -> plan/FUNCTION_MAP.md (committed)
python scripts/make_project_graph.py       # -> data/processed/project_graph.html

# Phase 3 benchmark — frozen-encoder baseline, 5-fold CV on LectureBank
python scripts/evaluate_classifier.py

# Phase 7 validator — synthetic-student recovery experiment (controlled)
python scripts/recovery_experiment.py                 # real LLM personas (default)
python scripts/recovery_experiment.py --mode structural  # offline (no quota)

# Live-UI smoke test — seed a scratch DB, then drive the student/faculty tabs' calls
python scripts/smoke_ui.py                            # seeds data/smoke_lecgap.db + a real clip
python scripts/smoke_drive.py                         # all checks should print PASS

# Phase 3 fine-tuned encoder (heavy) — run a Kaggle notebook on GPU, or a CPU smoke run:
python scripts/kaggle_fine_tune.py --epochs 1                # CPU smoke run
python scripts/kaggle_fine_tune.py --tune --base-model sentence-transformers/all-mpnet-base-v2  # hyperparam sweep
python scripts/make_kaggle_notebook.py                        # regenerate MiniLM notebook
python scripts/make_kaggle_notebook.py --backbone mpnet       # regenerate bigger-backbone notebook
```

Configuration:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(required for LLM/transcription features)* | `.env`; Groq chat + Whisper models |
| `WHISPER_BACKEND` | `local` | transcription engine: `local` (openai-whisper, offline) or `groq` (hosted, **~216× real-time**) |
| `WHISPER_MODEL` | `base` | local Whisper size (`tiny`…`large-v3`); ignored when `WHISPER_BACKEND=groq` |
| `GROQ_WHISPER_MODEL` | `whisper-large-v3-turbo` | hosted model used by `WHISPER_BACKEND=groq` ($0.04/audio-hour) |
| `GROQ_WHISPER_UPLOAD_LIMIT` | `25165824` | per-upload byte cap; audio is auto-chunked to fit |
| `LECGAP_DATABASE_URL` | `sqlite:///data/lecgap.db` | database location override |
| `LECGAP_GROQ_MODEL` | `openai/gpt-oss-20b` | chat model used by the pipeline |
| `LECGAP_OLLAMA_MODEL` / `LECGAP_OLLAMA_URL` | `llama3.2` / `http://127.0.0.1:11434` | final-fallback local backend |

Raw media and the database are git-ignored — never commit them.

## Docs index

| File | Contents |
|---|---|
| `plan/ARCHITECTURE.md` | Full 8-stage pipeline, stage by stage, tech stack |
| `plan/EVALUATION.md` | How the prerequisite classifier and refinement loop are tested |
| `plan/ROADMAP.md` | Phased build plan (complexity-based, not semester-bound) |
| `plan/DECISIONS.md` | Confirmed vs. open decisions, and why |
| `plan/LIMITATIONS.md` | Honest scope boundaries and known weak points |
| `plan/TEAM.md` | Roles, ownership, and risk notes |
| `plan/FUNCTION_MAP.md` | Auto-generated function inventory (what each module defines + consumes) — regenerate with `scripts/make_function_map.py` |
