# Roadmap

**Status: first draft, not yet reviewed line-by-line.** Only the
structuring principle below was actually agreed — phases ordered by
complexity, with continuous rolling estimates, not bound to semester
boundaries (since semester deadlines are administrative, not technical,
and are often not actually followed in practice). The specific phases and
time estimates here are a starting proposal to challenge and adjust, not
a locked plan. See `docs/DECISIONS.md`.

| Phase | What | Complexity | Rough estimate |
|---|---|---|---|
| 0 | Setup & research — repo, environment, read LectureBank paper/data, collect test lectures | Low | 1-2 weeks |
| 1 | Transcription pipeline (Whisper integration) | Low-Medium | 1-2 weeks |
| 2 | Concept extraction — spoken (LLM-based, explicit + implicit concepts) | Medium | 2-3 weeks |
| 2b | Concept extraction — visual (CLIP + OCR), can run in parallel with Phase 2 | Medium | 2 weeks |
| 3 | Prerequisite classifier — fine-tune pretrained embeddings, evaluate against LectureBank | High | 3-4 weeks |
| 4 | Graph construction — NetworkX DAG, dedup via embeddings, cycle resolution | Medium | 1-2 weeks |
| 5 | Clip segmentation (FFmpeg) | Low | 1 week |
| 6 | Student quiz loop — remediation ordering, in-app playback | Medium | 2 weeks |
| 7 | Refinement loop + synthetic-student recovery validation | High | 3-4 weeks |
| 8 | Faculty dashboard — confusion heatmap + taught-vs-learned divergence view | Medium | 2 weeks |
| 9 | Integration, testing, documentation, report | Medium | 2-3 weeks |

## If execution ends up mostly solo

See `docs/TEAM.md` — this is a live risk, not hypothetical. If it
materializes, cut priority (most to least cuttable, without touching the
project's actual claimed contribution in Phases 3 and 7):

1. Phase 8's divergence view — keep the confusion heatmap, drop the
   taught-vs-learned comparison first.
2. Phase 2b (visual track) — the system still functions on spoken
   concepts alone without it; document as future work instead.
3. Do not cut Phase 3 or Phase 7 — these are the project's actual
   technical claim (see `docs/EVALUATION.md`). Everything else exists to
   support and demonstrate them.
