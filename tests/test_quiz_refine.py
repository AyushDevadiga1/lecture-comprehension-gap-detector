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


# --------------------------------------------------------- refinement (Stage 7)

def test_run_refinement_round_reinforces_co_failures():
    from backend.pipeline.refine import run_refinement_round

    graph = {
        "edges": [{"source": "A", "target": "B", "confidence": 0.5}],
        "topological_order": ["A", "B"],
    }
    # all 4 students know A and master B -> strong support for A->B
    mastery = {i: ["A", "B"] for i in range(4)}
    rounds, summary = run_refinement_round(graph, mastery, n_students=4)
    assert rounds[0]["confidence"] > 0.5
    assert summary["n_students"] == 4


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