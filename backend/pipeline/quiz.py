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

  make_mcq(concept, evidence, pool) -> graded MCQ dict (options + answer)
                                   with the lecture's own spoken sentence as
                                   the stem, so the quiz is a real multiple-
                                   choice question, not a free-text probe.

  supporting_sentence(concept, segments)
                                -> the best transcript evidence for a concept.

Pure (no DB): takes an ordered graph (watched + failed) and produces watch
lists. Persistence + orchestration live in routes.py / db.py.
"""

import random
import re
from typing import Dict, Iterable, List, Optional, Tuple


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


# ---------------------------------------------------------------------------
# Stage 6b — MCQ generation. The quiz is a real multiple-choice question per
# concept (not a free-text probe): the stem quotes the spoken sentence from the
# lecture that describes the concept, and the distractors are the descriptions
# of *other* concepts (so an option only sounds right if the student actually
# knows the taught content). Answer/key are stored next to the distractors so
# grading is server-side.

_SPACE_RE = re.compile(r"\s+")
_DEFAULT_DISTRACTORS = (
    "It has no effect on the outcome",
    "It is entirely unrelated to the topic",
    "It contradicts everything stated",
)


def _clean(text: Optional[str], max_chars: int = 200) -> Optional[str]:
    """Normalize whitespace and cap a sentence for use as option text."""
    if not text:
        return None
    flat = _SPACE_RE.sub(" ", text).strip()
    return flat[:max_chars].rstrip()


def supporting_sentence(
    concept: str,
    segments: Iterable,
    max_chars: int = 200,
    skip: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Pick the transcript sentence that best supports a concept.

    Preference: the shortest segment that literally mentions the concept name
    (a spoken definition), else the longest piece of evidence available. The
    result is normalized and length-capped so it fits an option button.
    Segments may be dicts ({text, ...}) or objects with a `.text` attribute.

    ``skip`` holds already-used evidence texts; matching segments are ignored
    so successive concepts never share one "longest" fallback sentence.
    """
    skip = set(skip or ())
    candidate = None
    longest = None
    for seg in segments:
        text = _clean(
            seg.get("text") if isinstance(seg, dict) else getattr(seg, "text", None),
            max_chars,
        )
        if not text or text in skip:
            continue
        if longest is None or len(text) > len(longest):
            longest = text
        if concept.lower() in text.lower():
            if candidate is None or len(text) < len(candidate):
                candidate = text
    if candidate is None:
        candidate = longest
    return candidate


def make_mcq(
    concept: str,
    evidence: Optional[str],
    pool: Iterable[Tuple[str, Optional[str]]],
    rng: Optional[random.Random] = None,
) -> Dict:
    """Turn a concept into a graded MCQ dict.

    Args:
        concept:     the concept being tested.
        evidence:    the lecture sentence describing it (None -> fallback).
        pool:        iterable of (other_concept_name, other_evidence) pairs;
                     the other evidence are usable as plausible distractors.
        rng:         seeded Random for deterministic option shuffling.

    Returns:
        {"question": str, "options": List[str], "answer": str}. The correct
        option is always `answer`; fallback mode (no evidence anywhere) tests
        concept-name recognition so every question stays gradable.
    """
    rng = rng or random.Random(concept)

    if evidence is not None:
        answer = evidence
        distractors: List[str] = [e for _, e in pool if e and e != answer]
        distractors = list(dict.fromkeys(distractors))[:3]
        if len(distractors) < 3:
            need = 3 - len(distractors)
            distractors += list(_DEFAULT_DISTRACTORS[:need])
        question = (
            f"Which statement best describes the concept '{concept}' "
            "as taught in the lecture?"
        )
    else:
        # no lecture evidence at all -> the question is a recognition check
        # among the concept names, so it stays a valid, graded MCQ.
        answer = concept
        distractors = [n for n, _ in pool if n != concept]
        distractors = list(dict.fromkeys(distractors))[:3]
        if len(distractors) < 3:
            need = 3 - len(distractors)
            distractors += list(_DEFAULT_DISTRACTORS[:need])
        question = f"Which of these is the concept '{concept}'?"

    options = [answer] + distractors
    rng.shuffle(options)
    return {"question": question, "options": options, "answer": answer}
