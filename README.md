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

See `docs/EVALUATION.md` for how the prerequisite graph and refinement loop
are actually tested, and `docs/LIMITATIONS.md` for an honest account of
where this project's claims stop.

## Project status

Implementation underway, phased by complexity (see `plan/ROADMAP.md`):

- **Phase 0 — Setup & research: done.** Environment verified; test lectures in `data/raw/`.
- **Phase 1 — Transcription pipeline: done.** Lecture upload → background Whisper
  transcription → timestamped segments persisted to SQLite, served over the API.
  Verified end-to-end against a real CampusX lecture recording.
- **Next: Phase 2 — LLM-based concept extraction** (spoken/implicit concepts via Groq).

The technical core — prerequisite classification (Phase 3) and the refinement
loop (Phase 7) — is deliberately scheduled after this supporting infrastructure.

## Team

4 members, including Ayush. See `docs/TEAM.md` for roles and an honest
risk note on team reliability.

## Quickstart

```bash
# 1. Environment (conda; CPU-only PyTorch default so it works on any machine)
conda env create -f environment.yml
conda activate lecgap

# 2. Start the backend
uvicorn backend.main:app --reload          # API docs at http://127.0.0.1:8000/docs

# 3. Ingest a lecture (any ffmpeg-readable audio/video)
curl -X POST http://127.0.0.1:8000/lectures \
     -F "file=@my_lecture.mp4" -F "course_id=ml"

# 4. Poll until status is "ready", then read transcript segments
curl http://127.0.0.1:8000/lectures/1

# 5. (Later phases) Student / faculty UI
streamlit run frontend/app.py
```

Configuration: `WHISPER_MODEL` (default `base`) selects Whisper size;
`LECGAP_DATABASE_URL` overrides the SQLite location (`data/lecgap.db`).
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
