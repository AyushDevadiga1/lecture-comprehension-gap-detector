"""
Phase 7 — controlled synthetic-student recovery experiment (Claim 2).

This is the project's most original piece and the one requiring the most
care to present honestly (plan/EVALUATION.md, Claim 2; plan/LIMITATIONS.md
#5). It validates the REFINEMENT MECHANISM: can the loop recover a hidden
ground-truth graph from noisy, behavioral quiz signals?

Flow:
  1. Hidden ground-truth graph (answer key only; never an input to the
     pipeline).
  2. Synthetic students: each is generated to "know" a random subset of the
     hidden graph's concepts (see backend/pipeline/refine.py
     generate_synthetic_students); their quiz failures are the signal.
  3. A noisy "guessed" graph (the pipeline-like guess, imperfect).
  4. run_refinement_round improves guessed edge confidences from the
     students' co-failure signal.
  5. score_recovery reports edge precision/recall before vs. after.

Honest framing: this proves the mechanism in a controlled setting with a
known ground truth. It does NOT claim real human students behave like the
simulation — that is the stated boundary in EVALUATION.md and LIMITATIONS.md.

The full LLM-persona version (prompting an LLM to reason through each quiz
question given the known set) is future work; this script runs the numbers
with a transparent structural simulation so the code path is already
exercisable and evaluable.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.pipeline.refine import (  # noqa: E402
    generate_synthetic_students,
    run_refinement_round,
    score_recovery,
)

# 1. Hidden ground truth (structured chain: A<-B<-C, etc.)
HIDDEN_EDGES = [
    {"source": "PrereqA", "target": "CoreB", "confidence": 1.0},
    {"source": "CoreB", "target": "AdvancedC", "confidence": 1.0},
    {"source": "PrereqA", "target": "AdvancedC", "confidence": 1.0},
    {"source": "Independent", "target": "CoreB", "confidence": 1.0},
]
HIDDEN = {"edges": HIDDEN_EDGES, "topological_order": [
    "PrereqA", "Independent", "CoreB", "AdvancedC"]}

# 3. Imperfect "guessed" graph (as if the pipeline guessed it). One true edge
#    is slightly weak (CoreB->AdvancedC at 0.4) and one SPURIOUS edge is too
#    confident (PrereqA->Independent at 0.7). Refinement should fix both.
GUESSED_EDGES = [
    {"source": "PrereqA", "target": "CoreB", "confidence": 0.6},
    {"source": "CoreB", "target": "AdvancedC", "confidence": 0.4},  # weak, correct
    {"source": "PrereqA", "target": "AdvancedC", "confidence": 0.7},
    {"source": "PrereqA", "target": "Independent", "confidence": 0.7},  # wrong
]
GUESSED = {"edges": GUESSED_EDGES, "topological_order": [
    "PrereqA", "Independent", "CoreB", "AdvancedC"]}

HP = {(e["source"], e["target"]) for e in HIDDEN_EDGES}  # hidden edge set


def main() -> None:
    # 2. Synthetic students (structural personas: taught a random subset).
    students = generate_synthetic_students(HIDDEN, n=300, seed=7)
    # mastery signal: a student "masters" concepts they were taught. The
    # directional rule below prefers edges A->B where students who know A also
    # master B, and sinks edges whose successor is frequently NOT mastered.
    mastery = {f"s{i}": stu["known"] for i, stu in enumerate(students)}
    n_students = len(students)

    # 4. ONE refinement round over the observed cohort (do NOT re-loop the
    # same data — that double-counts the evidence and can oscillate). New
    # student cohorts would be additional, separate refinement rounds.
    before = score_recovery(GUESSED, HIDDEN)
    print(f"=== BEFORE refinement ===")
    print(f"precision={before['precision']:.3f} recall={before['recall']:.3f} "
          f"F1={before['f1']:.3f}")

    updated, _ = run_refinement_round(GUESSED, mastery, n_students)
    after_graph = {"edges": updated,
                   "topological_order": GUESSED["topological_order"]}
    after = score_recovery(after_graph, HIDDEN)
    print(f"\n=== AFTER one refinement round (N=300 synthetic students) ===")
    print(f"precision={after['precision']:.3f} recall={after['recall']:.3f} "
          f"F1={after['f1']:.3f}")
    print(f"\nF1: {before['f1']:.3f} -> {after['f1']:.3f} "
          f"({after['f1'] - before['f1']:+.3f})")
    print("\nedges after refinement (>= 0.5 counted):")
    for e in sorted(updated, key=lambda x: -x["confidence"]):
        pair = (e["source"], e["target"])
        mark = "OK" if pair in HP else "spurious"
        print(f"  {e['source']} -> {e['target']}: {e['confidence']:.3f} [{mark}]")


if __name__ == "__main__":
    main()