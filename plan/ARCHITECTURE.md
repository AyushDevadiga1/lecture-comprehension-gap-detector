# Architecture

## Pipeline overview

```
Lecture audio/video
      |
[1] Transcription (Whisper)
      |
[2] Concept Extraction (LLM for spoken/implicit concepts
      + CLIP/OCR for visual-only concepts)
      |
[3] Prerequisite Classification (fine-tuned pretrained
      embedding model + LLM reasoning cross-check)
      |
[4] Graph Construction (per-course concept DAG)
      |                                    \
[5] Clip Segmentation (FFmpeg)          [8] Faculty Dashboard
      |                                        ^
[6] Student Quiz Loop -> remediation           |
      |                                        |
[7] Refinement Loop ----------------------------
    (usage signals correct the graph over time)
```

## Stage 1 — Transcription

**Tool:** Whisper. Produces a transcript with word-level timestamps.
Standard, off-the-shelf — this stage is infrastructure, not a claimed
contribution.

## Stage 2 — Concept Extraction

Two parallel tracks feed into one concept list per lecture:

- **Spoken/implicit concepts:** an LLM reads transcript chunks and extracts
  concepts, including ones never explicitly named out loud (e.g. a lecture
  on overfitting may never say "bias-variance tradeoff," but the LLM can
  surface it as the underlying concept being taught).
- **Visual-only concepts:** CLIP (pretrained, zero-shot) matches sampled
  video frames to concept text, and OCR reads on-screen text (equations,
  slide bullet points, whiteboard writing) — catching anything shown but
  never spoken. Frames are sampled at scene changes, not every frame, to
  keep this tractable.

## Stage 3 — Prerequisite Classification (the technical core)

For candidate concept pairs (A, B), the system decides whether A is a
prerequisite of B. Two signals combine:

- A classifier built by **fine-tuning a pretrained embedding model**
  (not training from scratch — the labeled benchmark data is too small
  for that to be reliable) on prerequisite-pair data.
- An **LLM reasoning pass** that gives a second opinion and produces a
  human-readable explanation of *why* it believes A precedes B — this
  explanation is reused later in the faculty dashboard.

**Candidate pairs are pre-filtered**, not exhaustively checked — only
concepts that appear close together in time within the same lecture, or
that are semantically similar via embeddings, are passed to the
classifier. This avoids the pair count exploding as more concepts are
added.

**Evaluation benchmark:** LectureBank (the original 1.0 dataset — 1,352
lecture files, 60 courses, 208 manually labeled prerequisite topic pairs
across NLP, ML, AI, DL, and IR). This version was chosen over the larger
"LectureBank2.0" extension because that extension is described by its own
authors as drawn largely from NLP specifically, while LectureBank 1.0's
five-domain spread is a closer match to this project's ML/DL test
lectures. See `docs/EVALUATION.md` for full detail and primary sources.

## Stage 4 — Graph Construction

Confirmed prerequisite pairs become a directed graph (NetworkX). Cycles
are resolved via confidence-weighted topological sorting.

**Scope is per-course, not global.** The graph only ever contains concepts
that have actually appeared in the ingested lectures for a given course —
realistically 50-150 concepts, not an attempt at a universal concept bank
spanning all of human knowledge (that is a much larger, separate research
problem — see `docs/LIMITATIONS.md`).

**Deduplication:** as new lectures are added, newly extracted concepts are
checked against existing graph nodes via embedding similarity before being
added as new nodes, so "Gradient Descent" and "GD optimization" from
different lectures collapse into one node instead of two.

## Stage 5 — Clip Segmentation

**Tool:** FFmpeg. Cuts one clip per concept per timestamp range. Standard
infrastructure.

## Stage 6 — Student Quiz Loop

Student takes a quiz -> wrong answers are identified -> the prerequisite
graph determines the correct remediation order (not just "here's what you
got wrong," but "learn this first, because it's upstream of that") ->
clips are played back in-app in that order.

## Stage 7 — Refinement Loop

Real (or, pre-deployment, simulated) quiz-performance patterns are used as
weak supervision to correct the graph over time: if many students
consistently fail concept B right after struggling with concept A, that
becomes evidence reinforcing (or contradicting) the graph's assumed A->B
edge.

**This loop's validity is tested via a controlled synthetic-student
recovery experiment before any real deployment claim is made.** Full
methodology in `docs/EVALUATION.md` — this is the project's most original
piece, and also the one requiring the most care to present honestly.

## Stage 8 — Faculty Dashboard

- A confusion heatmap: per-concept, per-timestamp wrong-answer rates
  aggregated across students.
- A divergence view: where the order a concept was *taught* differs from
  the order the learned graph (and real quiz data) suggests it should have
  been *learned* — something no consumer AI study tool currently surfaces,
  since none of them have a concept of a classroom at all.

## Tech stack

| Component | Tool |
|---|---|
| Transcription | Whisper |
| Concept extraction (spoken) | LLM (Groq/Ollama) |
| Concept extraction (visual) | CLIP + OCR |
| Prerequisite classifier | PyTorch + HuggingFace pretrained embeddings (fine-tuned) |
| Graph | NetworkX + PyVis |
| Clip cutting | FFmpeg |
| Storage | SQLite |
| UI | Streamlit (student view + faculty view) |

## Decoupled architecture — PROPOSED, not yet confirmed

The team has agreed the system should use "a real professional decoupled
setup" rather than a monolithic script, but the specific framework split
has not been discussed or confirmed yet. A reasonable default — **not a
locked decision** — would be:

- A backend service (e.g. FastAPI) exposing the pipeline (stages 1-4, 7)
  as an API
- Streamlit (or another frontend) as a client consuming that API for the
  student and faculty views
- SQLite behind the API, not accessed directly by the frontend

This section should be reviewed and either confirmed or replaced before
implementation begins — see `docs/DECISIONS.md`.
