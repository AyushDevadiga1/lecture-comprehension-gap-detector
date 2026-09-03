"""
Phase 7 — controlled synthetic-student recovery experiment (Claim 2).

This is the project's most original piece and the one requiring the most
care to present honestly (plan/EVALUATION.md, Claim 2; plan/LIMITATIONS.md
#5). It validates the REFINEMENT MECHANISM: can the loop recover a hidden
ground-truth graph from noisy, behavioral quiz signals?

Flow:
  1. Hidden ground-truth graph (answer key only; never an input to the
     pipeline).
  2. Synthetic students via LLM personas (the plan's Claim 2 method): each
     persona is prompted to roleplay a student taught a randomized subset of
     the hidden graph's concepts, then genuinely attempts a knowledge-check
     for every concept given that taught set — producing realistic, patterned
     errors driven by its gaps (see backend/pipeline/refine.py
     generate_synthetic_students).
  3. A noisy "guessed" graph (the pipeline-like guess, imperfect).
  4. run_refinement_round improves guessed edge confidences from the
     students' mastery signal.
  5. score_recovery reports edge precision/recall/F1 before vs. after.

Running:
  python scripts/recovery_experiment.py                 # real LLM personas (default)
  python scripts/recovery_experiment.py --mode structural  # offline structural check
  python scripts/recovery_experiment.py --n 10 --seed 7    # smaller/faster

Honest framing: this proves the mechanism in a controlled setting with a
known ground truth. It does NOT claim real human students behave like the
simulation — that is the stated boundary in EVALUATION.md and LIMITATIONS.md.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

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


def structural_completer():
    """Deterministic fake 'persona' for offline smoke checks.

    A faithful analog of a well-reasoning LLM persona: a concept is mastered
    iff it was TAUGHT and every prerequisite in the hidden graph is also
    *mastered* (not merely taught) — i.e. full dependency-closure mastery.
    This is a bounded stand-in so the script can be smoke-tested without
    burning Groq quota.
    """
    prereqs = {}  # target -> list of sources that must be mastered first
    for e in HIDDEN_EDGES:
        prereqs.setdefault(e["target"], []).append(e["source"])

    def _mastered(concept, taught, memo):
        if concept in memo:
            return memo[concept]
        if concept not in taught:
            memo[concept] = False
            return False
        for p in prereqs.get(concept, []):
            if not _mastered(p, taught, memo):
                memo[concept] = False
                return False
        memo[concept] = True
        return True

    def completer(system, user, *, temperature=0.0):
        taught_line = [l for l in user.splitlines()
                       if l.startswith("Topics you were actually taught")]
        topic_line = [l for l in user.splitlines()
                      if l.startswith("Topic under test:")]
        taught = set()
        if taught_line:
            raw = taught_line[0].split(":", 1)[1]
            taught = {t.strip() for t in raw.split(",")
                      if t.strip() and t.strip() != "(none)"}
        topic = topic_line[0].split(":", 1)[1].strip() if topic_line else ""
        ok = _mastered(topic, taught, {})
        return type("R", (), {"text": "PASS" if ok else "FAIL"})()

    return completer


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["llm", "structural"], default="llm")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()

    if args.mode == "structural":
        # The completer below models a single persona's taught set, so we
        # curtail that usage here; for the structural check we instead rely on
        # the fake persona above.
        print("[mode=structural] offline deterministic personas (no LLM calls)")
        completer = structural_completer()
    else:
        print(f"[mode=llm] LLM-persona synthetic students "
              f"(n={args.n}, temp={args.temperature}) — uses Groq/Ollama quota "
              f"via llm.complete (cached on identical prompts)")
        completer = None  # default -> backend.pipeline.llm.complete

    # 2. Synthetic students (personas taught a random subset; genuine attempts).
    students = generate_synthetic_students(
        HIDDEN, n=args.n, seed=args.seed,
        completer=completer, temperature=args.temperature,
    )
    failures = {stu["id"]: stu["failed"] for stu in students}
    mastered_count = sum(len(stu["mastered"]) for stu in students)
    failed_count = sum(len(stu["failed"]) for stu in students)
    print(f"   {len(students)} personas; total mastered={mastered_count}, "
          f"failed={failed_count}")

    # 4. ONE refinement round over the observed cohort (do NOT re-loop the
    # same data — that double-counts the evidence and can oscillate). New
    # student cohorts would be additional, separate refinement rounds.
    before = score_recovery(GUESSED, HIDDEN)
    print(f"\n=== BEFORE refinement ===")
    print(f"precision={before['precision']:.3f} recall={before['recall']:.3f} "
          f"F1={before['f1']:.3f}")

    updated, _ = run_refinement_round(GUESSED, failures, len(students))
    after_graph = {"edges": updated,
                   "topological_order": GUESSED["topological_order"]}
    after = score_recovery(after_graph, HIDDEN)
    print(f"\n=== AFTER one refinement round (N={len(students)} synthetic students) ===")
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
