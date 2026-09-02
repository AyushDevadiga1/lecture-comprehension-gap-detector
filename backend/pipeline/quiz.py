"""
Stage 6 — Student Quiz Loop
See plan/ARCHITECTURE.md, Stage 6.

A student's wrong answers are mapped onto concepts, then the prerequisite
graph (Stage 4) determines the remediation order — not "here's what you got
wrong" but "study these first, because they're upstream of what you missed."

  order_quiz(values)            -> sort a course's concepts into a suggested
                                   quiz-taking order from the graph's learner
                                   order (optional).

  select_remediation_sequence(graph, failed_concepts)
                                -> the dependency-ordered clip/watch list for a
                                   student: the failed concepts plus everything
                                   upstream of them, lifted from the graph's
                                   topological (learner) order.

Pure (no DB): takes an ordered graph (watched + failed) and produces watch
lists. Persistence + orchestration live in routes.py / db.py.
"""

from typing import Dict, List


class _Graph:
    """Views used by this module. A real ConceptGraph provides these via its
    to_dict()/edges()/topological_order(); callers passing a dict use the
    constructor _from_dict below."""

    def __init__(self, edges: List[Dict], topological_order: List[str]):
        self.edges = edges
        self.order = topological_order

    @classmethod
    def _from_dict(cls, graph: Dict) -> "_Graph":
        return cls(graph.get("edges", []), graph.get("topological_order", []))


def order_quiz(topological_order: List[str]) -> List[str]:
    """Suggested quiz-taking order for a course — the graph's learner order.

    Prerequisites come before dependents, so a student who does poorly on an
    early question reveals gaps early. Values/labels untouched; this is just
    the ordering. Pure pass-through for completeness/tests.
    """
    return list(topological_order)


def select_remediation_sequence(
    graph: Dict, failed: List[str]
) -> List[Dict]:
    """Return the watch list for a student who failed `failed` concepts.

    Result is ordered by the graph's learner order (prerequisites first) and
    contains, for each watch item:
        {"concept": name, "failed": bool, "start_s": float,
         "end_s": float, "clip": Optional[str]}

    Scope = failed concepts ∪ everything upstream of them (transitive
    prerequisites). Watch items without a persisted clip get clip=None (the
    student view can still show the concept; playback is best-effort).
    """
    g = _Graph._from_dict(graph)
    failed_set = set(failed)

    # transitive closure of the prerequisite edges: upstream[B] = set of all
    # concepts that must be understood (directly or transitively) before B.
    n = len(g.order)
    order_index = {name: i for i, name in enumerate(g.order)}

    upstream: Dict[str, set] = {name: set() for name in g.order}
    # iterate edges repeatedly until fixpoint (small graphs: fine)
    changed = True
    while changed:
        changed = False
        for e in g.edges:
            src, tgt = e["source"], e["target"]
            if src in upstream and tgt in upstream and src not in upstream[tgt]:
                upstream[tgt].add(src)
                upstream[tgt] |= upstream[src]
                changed = True

    scope = set()
    for f in failed_set:
        scope.add(f)
        scope |= upstream.get(f, set())

    ordered = sorted(
        scope,
        key=lambda name: order_index.get(name, n),
    )
    return [
        {
            "concept": name,
            "failed": name in failed_set,
            "start_s": None,
            "end_s": None,
            "clip": None,
        }
        for name in ordered
    ]
