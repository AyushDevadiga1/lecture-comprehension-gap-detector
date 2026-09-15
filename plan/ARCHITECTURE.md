# Architecture

## Pipeline overview

```
Lecture audio/video
      |
[1] Transcription (Whisper)
      |
[1.5] Lecture-Structure pass (LLM): one sliding-window read emits
      passages (span/title/kind), per-concept teach-spans, and spoken
      prerequisite links with verbatim evidence
      |
[2] Concept set = structure concept teach-spans
      + CLIP/OCR for visual-only concepts
      |
[3] Prerequisite edges transcript-first; classifier falls back
      only for pairs the transcript never grounds
      |
[4] Graph Construction (per-course concept DAG; edges carry
      source_method + evidence)
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

## Stage 1.5 — Lecture-Structure pass (root-cause redesign, 2026-09-15)

The transcript is the richest artifact in the system — contiguous,
timestamped, natural-language *discourse*. Before the downstream stages are
allowed to re-derive weak proxies from it, ONE consolidated LLM read
(`backend/pipeline/passages.py`) recovers the lecture's structure:

- **Passages** — coherent teaching units, each with a title, `kind`
  (define/explain/worked_example/review/transition), a real time span, and
  the joined excerpt text used later for grounding.
- **Teach-spans** — per concept, *where it is actually taught* (definition,
  motivation, worked example), not a chunk stamp or a passing mention.
- **Spoken links** — prerequisite relations the professor voices ("before we
  can…", "recall…"), each with a verbatim `evidence` quote.

The transcript is read in sliding windows (8K chars, 25% overlap) with a
rolling header of prior passages, so a topic straddling a boundary is never
split invisibly and the caller pays for the whole structure in one pass
(~10 calls for a 60K-char lecture, deterministic prompts → cache hits).
Per-window parse failures degrade to skip/coarse spans; a whole-pass failure
falls back to the pre-redesign chunk-atomic extractor (`extract_concepts.py`
+ `refine_timeline.py`), which remain only as that rescue path. Full design:
`plan/LECTURE_STRUCTURE.md`.

## Stage 2 — Concept set (from the structure + visual track)

- **Spoken/implicit concepts** are the structure pass's concept list: every
  name already carries its teach-span, so no post-hoc refinement is needed.
  Implicit concepts (taught but never named aloud) are attached to the
  passage where they're actually taught with a real span.
- **Visual-only concepts:** CLIP (pretrained, zero-shot) matches sampled
  video frames to concept text, and OCR reads on-screen text (equations,
  slide bullet points, whiteboard writing) — catching anything shown but
  never spoken. Frames are sampled at scene changes, not every frame, to
  keep this tractable.

## Stage 3 — Prerequisite Classification (transcript-first, classifier as fallback)

For candidate concept pairs (A, B), the system decides whether A is a
prerequisite of B. The primary signal is the lecture itself:

- **Transcript-first:** prerequisite edges voiced in the lecture (the
  structure pass's `links`) are added at confidence 0.9 with their verbatim
  evidence — "the professor said so" is the strongest available evidence.
- **Classifier fallback:** a classifier built by **fine-tuning a pretrained
  embedding model** (not training from scratch — the labeled benchmark data
  is too small for that to be reliable) on prerequisite-pair data fills only
  the pairs the transcript never grounds — notably cross-lecture relations
  and silent jumps. The frozen-encoder baseline (F1 0.569) is retained in
  this role; same-call edge re-adds keep the higher confidence.
- An **LLM reasoning pass** remains available as a second opinion; its
  human-readable explanation is now backed by the transcript evidence quotes.

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

Confirmed prerequisite pairs become a directed graph (NetworkX). Edges
carry `source_method` (`"transcript"` @ 0.9 or `"classifier"`) and the
verbatim `evidence` for transcript edges. Cycles are resolved via
confidence-weighted topological sorting — transcript edges (0.9) dominate a
cycle by design, so the discourse wins over statistics.

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

**Tool:** FFmpeg. Cuts one clip per concept on its teach-span (the structure
pass's span, or the refined chunk span on the fallback path) with re-encode
by default so the cut is frame-accurate (`LECGAP_CLIP_STREAMCOPY=1` opts
back to `-c copy`). Standard infrastructure otherwise.

## Stage 6 — Student Quiz Loop

Student takes a quiz -> wrong answers are identified -> the prerequisite
graph determines the correct remediation order (not just "here's what you
got wrong," but "learn this first, because it's upstream of that") ->
clips are played back in-app in that order. Quiz questions are written by
the cached LLM from the concept's **teaching passage** (the structure
pass's joined excerpt), with an evidence-sentence fallback when no passage
anchors the concept.

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
- Edge **evidence**: every graph edge now carries `source_method` +
  `evidence`, so the DAG view can render *why* an edge exists — the verbatim
  "we build on X" quote, or the classifier's pair.

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
