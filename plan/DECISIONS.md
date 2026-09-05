# Decisions Log

This file exists for one reason: to keep the rest of the documentation
grounded in what was actually decided, rather than in anything proposed
and never confirmed. Every other doc in this repo should trace back to a
line in this file. When in doubt, this file wins.

## Confirmed

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

## Proposed — not yet confirmed

## How to use this file

Before adding a new architectural or methodological detail anywhere in
this repo, check: is it in the "Confirmed" list? If not, either get it
confirmed and move it up, or leave it clearly marked as proposed. Nothing
should quietly become "the plan" just because it was written down once.
