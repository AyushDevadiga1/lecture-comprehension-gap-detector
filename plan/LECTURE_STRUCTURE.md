# Lecture Structure Pass — root-cause redesign of Stages 2, 3, 5, 6

> **Status: APPROVED (2026-09-15) — design signed off; implementation phase B.
> Trigger: the `SYSTEM_EVAL.md` audit (2026-09-15) verified ~8 real defects and
> traced them to ONE root cause. This doc is the fix for that root cause. The
> decisions below are now Confirmed in `plan/DECISIONS.md`.

## 1. The root cause (why all 7 claims are one bug)

The transcript after Whisper is the richest artifact in the system: contiguous,
timestamped, natural-language **discourse** of an entire lecture. But the pipeline
never builds a discourse model from it. Each downstream stage re-derives a weak
proxy from an impoverished artifact, one shallow read at a time:

| Stage | Today's behavior | Root defect |
|---|---|---|
| 2 — extraction | Disjoint ~12K-char chunks, isolated concept lists, every concept stamped with the whole chunk's span (`extract_concepts.py:113-130`) | **Chunk-atomic, not discourse-aware.** The LLM is never asked *where* a concept is taught or how topics flow, so precision demands downstream repair |
| 2b — refine | Bolt-on patch re-reads bounded excerpts, substring first-mention, stride-samples implicit concepts, pads to 20 s, ~1 LLM call per wide concept (`refine_timeline.py`) | Compensates for the extraction granularity instead of fixing it — ~73 calls in the sample run (115 concepts, 42 tight) |
| 3 — prerequisites | `_pair_features` on two concept* names* (MiniLM), LectureBank-trained logistic head, `llm_reasoning_check` built but **never wired to any route** (`classify_prerequisites.py:209`) | Reads names, not the lecture. The transcript — where "before we can talk about backprop we need…" is *spoken* — is never opened |
| 5 — clips | Cut on the (coarse or refined) concept span; `-c copy` snaps to keyframes (`segment_clips.py`) | Tightness depends entirely on stage 2/2b getting real teach-spans |
| 6 — quiz | `local_context` = 3 segments (~15 s) around first mention (`mcq_gen.py:90-93`); verbatim-sentence fallback | No "teaching passage" exists to ground the writer, so it re-scans tiny windows |
| 8 — dashboard | Edges carry only a probability | No evidence/why is persisted even though stage 3's docs promise an explanation |

**Unifying statement:** the system has a transcript and a concept list, but no
notion of *what the lecture does* — no passages, no teach-spans, no discourse
structure. Everything downstream is therefore rebuilt weakly, in isolation, at
higher LLM cost than one structured read would cost.

## 2. Goal and non-goals

**Goal:** one consolidated, context-aware LLM read of the transcript produces a
per-lecture **structure** (passages + teach-spans + transcript-grounded
prerequisite links with evidence). Every later stage consumes that structure;
none re-scans the transcript shallowly. Net LLM calls for a full refresh **drop**
because the per-concept refinement (2b) and per-pair reasoning passes disappear.

**Non-goals (locked, out of scope):**
- No global concept bank — graph stays per-course (`plan/DECISIONS.md`, LIMITATIONS #4).
- No video/OCR track in this pass (visual concepts remain Phase 2b, cuttable).
- No retraining of the prerequisite classifier — the frozen baseline (F1 0.569)
  stays alive, **demoted to fallback** (see §6).
- No new per-concept LLM passes. Speed is preserved by *consolidation*, not by
  parallelizing more shallow reads.

## 3. The Lecture Structure pass

### 3.1 Input

`docs` — the same `[{start_s, end_s, text}]` whisper segments every stage already
consumes. Timestamps are real; whisper chunk re-assembly is unaffected (Groq
chunking/500-safety is unchanged, `transcribe.py`).

### 3.2 Windowing (context-aware, not chunk-atomic)

The lecture is read in **sliding windows** instead of disjoint chunks:

- `WINDOW_CHARS = 8000`, `OVERLAP_FRAC = 0.25` → a topic that spans a boundary
  is visible in both windows, so a passage is never split invisibly.
- Each window's prompt = the current excerpt **plus a compact rolling header**
  of prior passages (`title [start-end]`, one line each). This carries discourse
  continuity across the whole lecture for ~free — no extra calls — so the model
  sees the lecture it has already read, not just one isolated strip.
- Deterministic prompts, `temperature=0.0`, `max_tokens=800` → identical
  re-runs are SQLite-cache hits (zero cost, same as today's cache).

Call count: `ceil(lecture_chars / (WINDOW_CHARS × (1 - overlap)))`. For a
`~60K-char` lecture ≈ **10 calls** for the whole structure.

### 3.3 Output schema (per window, validated + clamped)

```json
{
  "passages": [
    {
      "title": "Why overfitting is a bias-variance tradeoff",
      "start_s": 402.1, "end_s": 518.6,
      "kind": "explain",
      "summary": "One sentence about what this passage teaches",
      "concepts": [
        {"name": "Bias-Variance Tradeoff", "implicit": true,
         "teach_start_s": 402.1, "teach_end_s": 455.0},
        {"name": "Regularization", "implicit": false,
         "teach_start_s": 455.0, "teach_end_s": 518.6}
      ],
      "continues": false
    }
  ],
  "links": [
    {"from": "Loss Function", "to": "Gradient Descent",
     "evidence": "to minimize the loss we take steps down its gradient"}
  ]
}
```

Rules the prompt enforces (these are what make the spans and edges *meaningful*):

- **Taught ≠ mentioned.** A concept's `teach_start_s..teach_end_s` covers the
  passage where it is *explained* (definition, motivation, worked example), not a
  passing mention. The model distinguishes `define / explain / worked_example /
  review / transition` via `kind`.
- **Implicit concepts** (never named aloud) are attached to the passage where
  they're actually taught with a real span — no stride-sampling hack.
- **Links** are prerequisite relations *said in the discourse* ("recall", "before
  we can", "this builds on"), each with a verbatim **evidence** quote, restricted
  to concepts that appear in the current excerpt.
- Bound the output: ≤ 4 passages per window, ≤ 6 concepts per passage, ≤ 8 links
  per window.

Parsing/validation mirrors today's hardened JSON handling (fence-stripping,
last-object fallback) and **clamps spans to the window bounds** exactly as
`refine_timeline._refine_one` clamps to the coarse window. Any parse failure in a
window keeps the coarse excerpt as a fallback passage (see §8) — the pass never
raises out of the worker.

### 3.4 Merge & normalize (pure, embedding-based, reused patterns)

- **Partial passages** (`continues: true`, span hits the window edge) merge with
  the continuation in the next window: span-overlap OR title-embedding ≥ 0.8.
- **Near-duplicate passages** reappearing in both windows merge by span-overlap
  > 70%.
- **Concept-name variants** across passages collapse via the existing embedding
  dedup recipe (`merge_concepts`, cosine ≥ 0.85).
- Output: `{passages: [...], concepts: [...] (each with passage_id + span),
  links: [...] (each with evidence)}` — a clean per-lecture structure.

## 4. Stage-by-stage rewiring

| Stage | After |
|---|---|
| 2 + 2b | `extract_lecture_structure(docs)` replaces `extract_spoken_concepts(docs)` + `refine_concept_times(...)`. Concepts carry precise teach-spans **from the pass itself**. `refine_timeline.py` is retained only as the fallback path (§8) |
| 3 | Prerequisite edges come **transcript-first** (the pass's `links`). The LectureBank classifier is the **fallback**: it fills pairs the transcript never grounded (cross-lecture relations, silent jumps) and returns to name-embedding dedup |
| 4 | `_rebuild_course_graph` (already extracted on 09-15) reads: lecture links → persist as `source_method="transcript"`, `confidence=0.9`; then classifier pairs **only for pairs not already linked** → `source_method="classifier"`. Cycle resolution unchanged (drops lowest-confidence edge) — transcript edges (0.9) dominate cycles by design, so discourse wins over statistics |
| 5 | Clips cut on teach-spans (already threaded through `_cut_clips_worker`). Re-encode default (09-15) stays |
| 6 | Quiz context = the persisted passage `text` for the concept's `passage_id`. `local_context` stays as a fallback for concepts with no passage. `generate_mcq` unchanged |
| 8 | `graph_edges` now carries `source_method` + `evidence`; the DAG view and divergence can render **why** an edge exists (the explanation ARCHITECTURE.md Stage 3 always promised) |

## 5. Data model changes (additive, precedent = quiz `_migrate_schema`)

- `passages`: `id`, `lecture_id`, `idx`, `title`, `kind`, `start_s`, `end_s`,
  `summary`, `text` (joined excerpt for quiz/clip grounding).
- `concepts`: add `passage_id` (nullable FK).
- `lecture_links`: `id`, `lecture_id`, `source_name`, `target_name`, `confidence`,
  `evidence` — per-lecture source of truth for transcript edges.
- `graph_edges`: add `source_method` (default `"classifier"`) and `evidence`
  (nullable).
- New tables via `init_db` `create_all`; new columns via additive `ALTER` so
  existing run DBs keep working (same pattern as the 09-14 quiz answer-key
  migration).

## 6. Prerequisite classifier: fallback role (your confirmed call)

The frozen baseline (F1 0.569) is **not deleted**. It becomes a fallback that:

1. fills pairs the transcript never explicitly grounds (notably **cross-lecture**
   — the pass reads one lecture; A-taught-here/precedes-B-taught-in-a-later-
   lecture is precisely what a name-level look learns), and
2. keeps name-embedding dedup for graph nodes.

Edge priority in the merge: transcript (0.9) > classifier (0.5-0.7 as today).
This preserves the Phase 3 work as a *component* while making the discourse the
primary signal — with the `llm_reasoning_check` finally realizeable as the
faculty "why" (evidence quotes) instead of an unwired extra pass.

## 7. Speed & quota budget (the "don't kill speed" constraint)

For the refreshed sample lecture (~115 concepts, ~60K chars):

| Path | LLM calls for a full refresh | Notes |
|---|---|---|
| **Old** | 5 (extraction) + **≈73 (refine 2b)** + ~88 (MCQ) ≈ **166** | refinement is the hidden tax of chunk-atomic extraction |
| **New** | **≈10 (structure pass)** + ~88 (MCQ) ≈ **98** | passages+spans+edges+evidence all from the same 10 reads |

- Per-window prompt ≈ 2K input + ≤800 output tokens — well inside the Groq
  Developer window (30 req/8K tok/min, `llm.py` docstring), no burst.
- The **consolidation is the speed win**: one structured read replaces the
  scattered shallow reads, and re-runs stay cache-free via identical prompts.
- Quiz MCQ calls are unchanged (inherently one-per-question) but now land on real
  passage text → fewer verbatim fallbacks, better `explanation`/`rationale` rate.

## 8. Failure isolation & fallback

The pass is the happy path; the old path is the safety valve:

- If **any window** fails to parse: that window degrades to a coarse passage
  covering its span (concepts keep coarse times), never a crash.
- If the **whole pass** fails (LLM backend down): `_extract_concepts_worker`
  falls back to today's `extract_spoken_concepts` + `refine_concept_times` so a
  user is never stranded. Simplicity of the old path remains as the rescue rope.
- The fallback is a code-path toggle, not a second system: one worker, one flow,
  one decision at the top.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM span drift (bad teach-spans) | Clamp to window; require span-window overlap; pad short spans to the 20 s watchable minimum (existing `MIN_TIGHT_S` logic, reused) |
| Merge creates duplicate concepts/edges | Reuse existing embedding dedup + max-confidence edge merge; assert per-course invariants in tests (`is_dag`, no dup edges) |
| Output token bloat over a window | Strict caps (§3.3) + validation drops over-long arrays |
| Cross-window links missed | Rolling header of prior passages carries continuity; classifier fallback catches the rest |
| Regression of today's chaining fix | New API test asserts extraction worker persists passages+links and the graph rebuild consumes them first |

## 10. Test plan

- **Unit (`passages.py`):** window sliding (boundaries/overlap), JSON parse +
  clamp validation, `continues` merging, dedup (embedding, hand vectors as in
  `test_build_graph.py`), budget caps, windows→teach-span mapping, promise: no
  per-concept LLM call (count injected completer calls).
- **API:** extraction worker persists `passages`+`concepts.passage_id`+
  `lecture_links`; `_rebuild_course_graph` prefers transcript edges then classifies
  only uncovered pairs; `create_quiz` reads passage text; old `local_context`
  fallback still covered; existing suite stays green (target ≥ 150).
- **Eval on the committed sample** (post-implementation): tight-window share
  jumps from 42/115 toward ~all; median window well under the 666.9 s baseline;
  edge `source_method` split recorded; quiz explanation rate up; refresh call
  count down. Recorded in `WORKLOG.md` §9.

## 11. Rollout (docs → prototype → wire → refresh)

1. ✅ Sign off this doc (2026-09-15) + confirm decisions in `plan/DECISIONS.md`.
2. **Prototype first, on small sections** *(user directive: quality over scale —
   smoke-test ~2-3 min slices of real transcript, eyeball passages/teach-spans/
   edge evidence, scale up only once quality holds).* Run the pass over slices of
   the committed sample transcript (temperature 0, cached) before wiring anything.
3. Schema + `backend/pipeline/passages.py` with unit tests.
4. Wire worker + graph merge + quiz context; `.env` knobs for window size.
5. Refresh the sample run (`scripts/refresh_run.py`); compare the §10 eval
   metrics; commit artifacts.
6. Update `plan/ARCHITECTURE.md`, `plan/FUNCTION_MAP.md`, README, WORKLOG.