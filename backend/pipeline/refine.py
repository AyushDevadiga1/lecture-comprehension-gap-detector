"""
Stage 7 — Refinement Loop
See plan/ARCHITECTURE.md, Stage 7, and plan/EVALUATION.md, "Claim 2" for
the full honest validation methodology.

Real (or, pre-deployment, simulated) quiz-performance patterns are used
as weak supervision to correct the graph over time.

  generate_synthetic_students(hidden_graph, n)  -> LLM personas that
                                                    genuinely reason
                                                    through quiz
                                                    questions based on a
                                                    randomized "known
                                                    concepts" subset —
                                                    NOT random noise.

  run_refinement_round(graph, quiz_results)     -> updates edge
                                                    confidences based on
                                                    observed
                                                    failure patterns.

  score_recovery(guessed_graph, hidden_graph)   -> edge-accuracy
                                                    before/after, for the
                                                    controlled recovery
                                                    experiment.

IMPORTANT: keep the synthetic-student validation code in a clearly
separate module/script from anything that touches real quiz data, so the
report can honestly distinguish "controlled proof of mechanism" from
"real classroom result" (see plan/LIMITATIONS.md, #5).
"""

# TODO (Phase 7): implement generate_synthetic_students,
# run_refinement_round, score_recovery. This is the project's most
# original piece — budget the most review time here.
