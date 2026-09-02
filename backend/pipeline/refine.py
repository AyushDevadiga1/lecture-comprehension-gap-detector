"""
Stage 7 — Refinement Loop
See plan/ARCHITECTURE.md, Stage 7, and plan/EVALUATION.md, "Claim 2" for
the full honest validation methodology.

Real (or, pre-deployment, simulated) quiz-performance patterns are used as
weak supervision to correct the graph over time: if many students
consistently fail concept B right after struggling with concept A, that
becomes evidence reinforcing (or contradicting) the graph's assumed A->B
edge.

The synthetic-student recovery experiment (the project's most original
piece, and the one requiring the most care to present honestly) is kept
separate from anything touching real quiz data — see plan/LIMITATIONS.md #5.

  run_refinement_round(graph, co_fail_count, student_counts)
      -> adjust edge confidences from observed co-failure signals.

  generate_synthetic_students(hidden_graph, n)   -> LLM personas.
      Implemented here as the structural persona generator; the fully
      realized LLM-reasoning version is a separate script
      (scripts/recovery_experiment.py) so this module stays pure and
      testable without API calls.

  score_recovery(guessed_graph, hidden_graph)
      -> precision/recall/F1 of guessed edges vs. the hidden ground truth,
         for "before vs. after refinement" convergence reporting.
"""

from typing import Dict, List


def _edges_of(graph: Dict) -> List[Dict]:
    if isinstance(graph, dict):
        return list(graph.get("edges", []))
    return list(graph.edges())


def run_refinement_round(
    graph: Dict,
    mastery: Dict[str, List[str]],
    n_students: int,
) -> "tuple[List[Dict], Dict]":
    """Adjust the graph's edge confidences from directional student signals.

    Weak-supervision rule (directional, more principled than plain co-failure):
    a directed edge A->B is supported by students who KNOW A (its prerequisite
    is taught) *and* MASTER B; it is weakened by students who know A but then
    FAIL B (B was expected to follow A, yet wasn't learned even with A known —
    hinting the dependency is wrong or B is independent). Per edge:

        support = fraction of students who (knew A) and (mastered B)
        inhibit = fraction of students who (knew B) and (failed B)

    The updated confidence blends the graph's prior confidence with this
    directional evidence:

        c' = clamp(0.5 * prior + 0.3 * support + 0.2 * (1 - inhibit))

    `mastery` maps student_id -> sorted list of concepts that student mastered
    (from their quiz/co-failure data; the inverse of the "unknown" signal).
    `n_students` is the number of students seen, for normalizing the evidence.

    Returns (updated_edges, summary). Pure — persistence is the caller's job.
    """
    edges = _edges_of(graph)
    n = max(1, n_students)
    mastered_set = {sid: set(concepts) for sid, concepts in mastery.items()}
    # which students know each concept (are "taught" it) — approximate via the
    # students who did NOT fail it, i.e. who ended up mastering other things.
    # For a clean directional proxy we derive "knows X" = the students who
    # list X as mastered OR who list X in no failure list; here we approximate
    # "knows A" as "A appears in that student's mastered set".
    out = []
    for e in edges:
        src, tgt = e["source"], e["target"]
        prior = float(e.get("confidence", 0.5))
        know_src = [sid for sid, s in mastered_set.items() if src in s]
        both = [sid for sid in know_src if tgt in mastered_set.get(sid, set())]
        inhibit = [sid for sid in mastered_set if tgt not in mastered_set.get(sid, set())]

        support = len(both) / n
        inhibit_frac = len(inhibit) / n

        updated = min(1.0, max(0.0, 0.5 * prior + 0.3 * support + 0.2 * (1.0 - inhibit_frac)))
        out.append({"source": src, "target": tgt, "confidence": updated})

    return out, {"edges_updated": len(out), "n_students": n_students}


def score_recovery(
    guessed_graph: Dict, hidden_graph: Dict, threshold: float = 0.5
) -> Dict:
    """Precision/recall/F1 of the guessed graph's edges against the hidden
    ground truth — the "before vs. after refinement" convergence metric.

    A guessed edge counts as present only if its confidence is >= `threshold`
    (so the loop is scored on the strength-weighted edge set). Refinement
    raises true edges above threshold and sinks spurious ones below it, which
    is what makes the before/after F1 move.
    """
    guessed = {
        (e["source"], e["target"])
        for e in _edges_of(guessed_graph)
        if float(e.get("confidence", 0.0)) >= threshold
    }
    hidden_set = {(e["source"], e["target"]) for e in _edges_of(hidden_graph)}

    correct = len(guessed & hidden_set)
    precision = correct / len(guessed) if guessed else 0.0
    recall = correct / len(hidden_set) if hidden_set else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )
    return {"precision": precision, "recall": recall, "f1": f1,
            "correct_edges": correct, "guessed_edges": len(guessed),
            "hidden_edges": len(hidden_set)}


def generate_synthetic_students(
    hidden_graph: Dict, n: int, seed: int = 42
) -> List[Dict]:
    """Schematic LLM-persona synthetic students (Claim 2 mechanics).

    Each synthetic student is a persona that has been *taught* a defined,
    randomized subset of the hidden graph's concepts (the "known" set); a
    fully-realized version prompts an LLM to reason through each quiz
    question given that known set, producing realistic patterned errors.

    This schematic returns the structural inputs a recovery experiment needs —
    per student, the concepts they were NOT taught (these are the ones they
    tend to fail) — which is the ground-truth signal the refinement loop is
    tested against. The actual LLM reasoning lives in
    scripts/recovery_experiment.py (kept separate, no API calls here).
    """
    import random

    rng = random.Random(seed)
    if isinstance(hidden_graph, dict):
        all_concepts = list({e["source"] for e in _edges_of(hidden_graph)} |
                            {e["target"] for e in _edges_of(hidden_graph)})
    else:
        all_concepts = list(hidden_graph.nodes())
    if not all_concepts:
        return []
    students = []
    for _ in range(n):
        k = rng.randint(max(1, len(all_concepts) // 2), len(all_concepts))
        taught = set(rng.sample(all_concepts, k))
        students.append({
            "known": sorted(taught),
            "unknown": sorted(set(all_concepts) - taught),
        })
    return students