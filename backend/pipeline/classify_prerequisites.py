"""
Stage 3 — Prerequisite Classification (the project's technical core)
See plan/ARCHITECTURE.md, Stage 3, and plan/EVALUATION.md for the full
evaluation methodology.

For candidate concept pairs (A, B): does A need to be understood before B?

  get_candidate_pairs(concepts)     -> pre-filters which pairs are even
                                        worth checking (close in time, or
                                        semantically similar via
                                        embeddings) — NOT exhaustive,
                                        see plan/ARCHITECTURE.md for why.

  classify_pair(a, b)               -> fine-tuned pretrained embedding
                                        model's prediction + confidence.

  llm_reasoning_check(a, b)         -> second-opinion LLM pass that also
                                        produces a human-readable
                                        explanation (reused later in the
                                        faculty dashboard).

Evaluation target: LectureBank 1.0 (208 labeled pairs, 5 domains).
Do not train from scratch — fine-tune only (confirmed in
plan/DECISIONS.md); cross-validate rather than a single train/test split.
"""

# TODO (Phase 3): implement get_candidate_pairs, classify_pair,
# llm_reasoning_check. Add a separate eval script (scripts/evaluate_classifier.py,
# not yet created) that scores against data/lecturebank/.
