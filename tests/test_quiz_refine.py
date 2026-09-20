"""
Tests for the quiz loop (Phase 6) and refinement loop (Phase 7).

Pure-logic only. The API integration (routes) is covered separately by the
api fixture in test_api.py; here we test the pipeline functions directly and
the refinement/score functions against hand-built graphs.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# ------------------------------------------------------------- quiz (Stage 6)

def test_select_remediation_sequence_upstream_only():
    from backend.pipeline.quiz import select_remediation_sequence

    graph = {
        "edges": [
            {"source": "A", "target": "B", "confidence": 0.9},
            {"source": "B", "target": "C", "confidence": 0.8},
            {"source": "D", "target": "E", "confidence": 0.7},
        ],
        "topological_order": ["A", "B", "C", "D", "E"],
    }
    seq = select_remediation_sequence(graph, failed=["C"])
    concepts = [x["concept"] for x in seq]
    # A and B are upstream of C; D, E are unrelated so excluded
    assert concepts == ["A", "B", "C"]
    flags = {x["concept"]: x["failed"] for x in seq}
    assert flags == {"A": False, "B": False, "C": True}


def test_select_remediation_sequence_marks_failed():
    from backend.pipeline.quiz import select_remediation_sequence

    graph = {
        "edges": [{"source": "A", "target": "B", "confidence": 0.9}],
        "topological_order": ["A", "B"],
    }
    seq = select_remediation_sequence(graph, failed=["A", "B"])
    flags = {x["concept"]: x["failed"] for x in seq}
    assert flags == {"A": True, "B": True}


def test_select_remediation_sequence_empty_failed():
    from backend.pipeline.quiz import select_remediation_sequence

    graph = {"edges": [{"source": "A", "target": "B", "confidence": 0.9}],
             "topological_order": ["A", "B"]}
    assert select_remediation_sequence(graph, failed=[]) == []


def test_order_quiz_passthrough():
    from backend.pipeline.quiz import order_quiz

    assert order_quiz(["A", "B", "C"]) == ["A", "B", "C"]


# ---------------------------------------------------- MCQ generation (Stage 6b)

def test_make_mcq_uses_lecture_evidence_as_answer():
    from backend.pipeline.quiz import make_mcq

    evidence = "the gradient shows the slope of the loss surface"
    q = make_mcq(
        "gradient",
        evidence,
        pool=[("overfit", "the model memorizes the training set"),
              ("dropout", "randomly silences some neurons"),
              ("epoch", "one full pass over the data")],
        rng=__import__("random").Random(1),
    )
    assert "gradient" in q["question"]
    assert q["answer"] == evidence
    assert len(q["options"]) == 4
    assert q["answer"] in q["options"]
    # distractors come from other concepts' spoken evidence, not the answer
    assert "gradient" not in " ".join(o for o in q["options"] if o != evidence)


def test_make_mcq_deterministic_given_seed():
    from random import Random

    from backend.pipeline.quiz import make_mcq

    kwargs = dict(
        concept="c", evidence="the definition of c",
        pool=[("d", "the definition of d"), ("e", "the definition of e")],
    )
    a = make_mcq(**kwargs, rng=Random(42))
    b = make_mcq(**kwargs, rng=Random(42))
    assert a["options"] == b["options"]


def test_make_mcq_fallback_keeps_question_gradable():
    from backend.pipeline.quiz import make_mcq

    q = make_mcq("attention", None, pool=[("memory", None), ("rnn", None)])
    assert q["answer"] == "attention"
    assert q["answer"] in q["options"]
    assert len(q["options"]) >= 2


def test_supporting_sentence_prefers_mentions_then_longest():
    from backend.pipeline.quiz import supporting_sentence

    segs = [
        {"start_s": 0, "end_s": 10, "text": "a very long passage that only discusses "
          "the training loop and never once mentions the word drop out okay"},
        {"start_s": 10, "end_s": 12, "text": "dropout randomly silences neurons"},
    ]
    assert supporting_sentence("dropout", segs) == "dropout randomly silences neurons"
    # no mention anywhere -> the longest segment is used as fallback evidence
    assert supporting_sentence("lstm", segs) == segs[0]["text"]


def test_supporting_sentence_skip_avoids_reusing_evidence():
    from backend.pipeline.quiz import supporting_sentence

    segs = [
        {"start_s": 0, "end_s": 10, "text": "the shared concept definition"},
        {"start_s": 10, "end_s": 20, "text": "a different segment entirely"},
    ]
    first = supporting_sentence("alpha", segs)
    assert first == "the shared concept definition"
    # the "longest" fallback must not hand the same sentence to the next concept
    second = supporting_sentence("beta", segs, skip={first})
    assert second != first


def test_make_mcq_fallback_uses_concept_names_as_options():
    from backend.pipeline.quiz import make_mcq

    q = make_mcq("attention", None, pool=[("memory", None), ("rnn", None)])
    assert q["answer"] == "attention"
    assert set(q["options"]) == {"attention", "memory", "rnn",
                                 "It has no effect on the outcome"}


# --------------------------------------------------------- refinement (Stage 7)

def test_run_refinement_round_reinforces_co_failures():
    from backend.pipeline.refine import run_refinement_round

    graph = {
        "edges": [{"source": "A", "target": "B", "confidence": 0.5}],
        "topological_order": ["A", "B"],
    }
    # all 4 students fail A AND B together -> strong evidence that B depends on A
    failures = {i: ["A", "B"] for i in range(4)}
    rounds, summary = run_refinement_round(graph, failures, n_students=4)
    assert rounds[0]["confidence"] > 0.5
    assert summary["n_students"] == 4


def test_run_refinement_round_sinks_spurious_edge():
    from backend.pipeline.refine import run_refinement_round

    graph = {
        "edges": [{"source": "A", "target": "B", "confidence": 0.7}],
        "topological_order": ["A", "B"],
    }
    # all 4 students fail A but succeed at B -> B does NOT depend on A -> sink
    failures = {i: ["A"] for i in range(4)}
    rounds, _ = run_refinement_round(graph, failures, n_students=4)
    assert rounds[0]["confidence"] < 0.5


def test_run_refinement_round_no_failures_is_neutral():
    from backend.pipeline.refine import run_refinement_round

    graph = {
        "edges": [{"source": "A", "target": "B", "confidence": 0.6}],
        "topological_order": ["A", "B"],
    }
    # nobody fails anything -> no signal -> confidence stays at the prior blend
    rounds, _ = run_refinement_round(graph, {}, n_students=5)
    assert rounds[0]["confidence"] == 0.5 * 0.6


# ------------------------------------------------------- synthetic personas (Claim 2)

def _concept_in_user(user: str) -> str:
    """Extract the concept name from the delimited `Topic under test:` block:
    the line following the enclosing <lecture_data> tag that comes after the
    label."""
    rest = user[user.rfind("Topic under test:"):]
    start_marker = rest.find("<lecture_data")
    close_bracket = rest.find(">", start_marker)
    end = rest.find("</lecture_data>")
    if close_bracket == -1 or end == -1:
        return ""
    return rest[close_bracket + 1:end].strip()


def _fake_completer(pass_set):
    def fake(system, user, *, temperature=0.0):
        return type("R", (), {"text": "PASS" if _concept_in_user(user) in pass_set else "FAIL"})()
    return fake


def test_generate_synthetic_students_collects_passes_fails():
    from backend.pipeline.refine import generate_synthetic_students

    hidden = {
        "edges": [
            {"source": "A", "target": "B", "confidence": 1.0},
            {"source": "B", "target": "C", "confidence": 1.0},
            {"source": "X", "target": "Y", "confidence": 1.0},
        ],
        "topological_order": ["A", "B", "C", "X", "Y"],
    }
    students = generate_synthetic_students(
        hidden, n=3, seed=1, completer=_fake_completer({"A", "B", "C"})
    )
    assert len(students) == 3
    for s in students:
        assert s["id"].startswith("s")
        assert set(s["mastered"]) == {"A", "B", "C"}
        assert set(s["failed"]) == {"X", "Y"}
        assert isinstance(s["taught"], list) and s["taught"]


def test_generate_synthetic_students_empty_graph():
    from backend.pipeline.refine import generate_synthetic_students

    assert generate_synthetic_students({"edges": []}, n=4, completer=_fake_completer(set())) == []


def test_generate_synthetic_students_guard_and_delimit():
    """M1: persona prompts carry the DATA_GUARD and delimit BOTH the taught
    topic set and the concept-under-test block (lecture-derived names are
    untrusted data), while keeping `Topic under test:` parseable."""
    from backend.pipeline.prompt_guard import CLOSE_TAG, DATA_GUARD, OPEN_TAG
    from backend.pipeline.refine import generate_synthetic_students

    seen = {"system": None, "user": None}

    def spy(system, user, *, temperature=0.0):
        seen["system"] = system
        seen["user"] = user
        return type("R", (), {"text": "PASS" if _concept_in_user(user) in {"A", "B"} else "FAIL"})()

    out = generate_synthetic_students(
        {"edges": [{"source": "A", "target": "B", "confidence": 1.0}],
         "topological_order": ["A", "B"]},
        n=1, seed=1, completer=spy,
    )
    assert out and len(out[0]["mastered"]) == 2
    assert DATA_GUARD in seen["system"]
    assert OPEN_TAG in seen["user"] and CLOSE_TAG in seen["user"]
    assert "Topic under test:" in seen["user"]


def test_concepts_of_includes_sources_and_targets():
    from backend.pipeline.refine import _concepts_of

    g = {"edges": [{"source": "A", "target": "B", "confidence": 1.0},
                   {"source": "B", "target": "C", "confidence": 1.0}]}
    assert _concepts_of(g) == ["A", "B", "C"]


# ----------------------------------------------------------- scoring (Claim 2)

def test_score_recovery_edge_accuracy():
    from backend.pipeline.refine import score_recovery

    guessed = {
        "edges": [
            {"source": "A", "target": "B", "confidence": 0.9},
            {"source": "B", "target": "C", "confidence": 0.8},
            {"source": "A", "target": "D", "confidence": 0.7},  # not in hidden
        ]
    }
    hidden = {
        "edges": [
            {"source": "A", "target": "B", "confidence": 1.0},
            {"source": "B", "target": "C", "confidence": 1.0},
        ]
    }
    res = score_recovery(guessed, hidden)
    # 2 correct of 3 guessed edges; 2 of 2 hidden recovered
    assert res["precision"] == pytest.approx(2 / 3)
    assert res["recall"] == 1.0
    assert res["f1"] == pytest.approx(2 * (2 / 3) * 1.0 / ((2 / 3) + 1.0))