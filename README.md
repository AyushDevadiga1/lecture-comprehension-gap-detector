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
- **Phase 3 — Prerequisite classification (core): baseline done, fine-tune in progress.**
  - `backend/pipeline/classify_prerequisites.py` — candidate-pair pre-filter
    (temporal + embedding similarity) and a **fine-tuned-classifier** baseline:
    frozen MiniLM encoder + logistic head over the LectureBank pairs.
  - `scripts/evaluate_classifier.py` — nested 5-fold CV with honest
    threshold selection; **F1 0.569** on LectureBank 1.0.
  - Fine-tuning infrastructure for the transformer encoder is in
    `backend/pipeline/fine_tune.py` (with `weight_decay`/`grad_clip` support),
    `scripts/kaggle_fine_tune.py` (`--tune` sweep, `--base-model`,
    `--weight-decay`, `--grad-clip`, `--metrics-out`), and two self-contained
    notebooks for Kaggle GPU:
    - `notebooks/kaggle_fine_tune.ipynb` — MiniLM backbone push (epochs 8/10/12).
    - `notebooks/kaggle_fine_tune_mpnet.ipynb` — bigger backbone
      (`all-mpnet-base-v2`), the current "better alternative" experiment.
  - Both notebooks stage results to `metrics.json` and only ship
    `/kaggle/working/model/` via a manual FINALIZE cell if the CV F1 beats the
    frozen baseline (0.569). So far the cross-encoder keeps improving with
    epochs (e3→0.49, e5→0.53, **e8→0.554**) but has **not yet** out-scored the
    frozen encoder — a decision is pending on the latest (both) GPU runs.

The refinement loop (Phase 7) remains the second core claim, scheduled after
this infrastructure is stable.

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
# Unit tests (stubbed LLM — zero API usage, isolated test DB)
python -m pytest tests

# Phase 3 benchmark — frozen-encoder baseline, 5-fold CV on LectureBank
python scripts/evaluate_classifier.py

# Phase 3 fine-tuned encoder (heavy) — run a Kaggle notebook on GPU, or a CPU smoke run:
python scripts/kaggle_fine_tune.py --epochs 1                # CPU smoke run
python scripts/kaggle_fine_tune.py --tune --base-model sentence-transformers/all-mpnet-base-v2  # hyperparam sweep
python scripts/make_kaggle_notebook.py                        # regenerate MiniLM notebook
python scripts/make_kaggle_notebook.py --backbone mpnet       # regenerate bigger-backbone notebook
```

Configuration:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(required for LLM features)* | `.env`; Groq chat models |
| `WHISPER_MODEL` | `base` | local Whisper size (`tiny`…`large-v3`) |
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
