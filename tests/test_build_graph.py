"""
Tests for Stage 4 graph construction (backend/pipeline/build_graph.py).

Pure-logic only: the embedding encoder is monkeypatched with tiny hand-made
vectors, so no model download, no LectureBank file, no API calls. DB
persistence is exercised against an in-memory SQLite engine.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# Hand-made vectors: "Gradient Descent" and "GD optimization" are intended to
# be near-cosine (dedup should merge them); everything else is far apart.
def _hand_vecs():
    base = {
        "Gradient Descent": np.array([1.0, 0.0, 1.0, 0.0]),
        "GD optimization": np.array([0.95, 0.0, 0.9, 0.0]),
        "Loss Function": np.array([0.0, 1.0, 0.0, 1.0]),
        "Cross Entropy": np.array([0.0, 1.0, 0.3, 0.0]),
        "Neural Network": np.array([1.0, 1.0, 0.0, 0.0]),
    }
    return base


def _make_graph(dedup_threshold=0.85):
    from backend.pipeline.build_graph import ConceptGraph

    vecs = _hand_vecs()
    g = ConceptGraph(dedup_threshold=dedup_threshold)

    def fake_vec(name):
        return vecs.get(name, np.zeros(4))

    g._vec = fake_vec
    return g


def test_add_concepts_returns_canonical_per_input():
    g = _make_graph()
    out = g.add_concepts(["Loss Function", "Cross Entropy"])
    assert out == ["Loss Function", "Cross Entropy"]
    assert g.node_count == 2


def test_add_concepts_dedups_via_embedding_similarity():
    g = _make_graph()
    canonical = g.add_concepts(["Gradient Descent", "GD optimization"])
    assert canonical[0] == "Gradient Descent"
    assert canonical[1] == "Gradient Descent"  # merged into one node
    assert g.node_count == 1


def test_add_concepts_exact_duplicate_deduped():
    g = _make_graph()
    out = g.add_concepts(["Loss Function", "Loss Function", "Cross Entropy"])
    assert out == ["Loss Function", "Loss Function", "Cross Entropy"]
    assert g.node_count == 2


def test_add_concepts_does_not_merge_dissimilar_names():
    g = _make_graph()
    out = g.add_concepts(["Gradient Descent", "Loss Function"])
    assert out == ["Gradient Descent", "Loss Function"]
    assert g.node_count == 2


def test_add_concepts_blank_names_skipped():
    g = _make_graph()
    assert g.add_concepts(["Loss Function", "  ", ""]) == ["Loss Function", "", ""]
    assert g.node_count == 1


def test_build_graph_from_pairs_dedups_edge_endpoints(monkeypatch):
    from backend.pipeline.build_graph import ConceptGraph, build_graph_from_pairs

    vecs = _hand_vecs()
    monkeypatch.setattr(
        ConceptGraph, "_vec", lambda self, name: vecs.get(str(name), np.zeros(4))
    )

    graph, removed = build_graph_from_pairs(
        ["Gradient Descent", "GD optimization"],
        [("GD optimization", "Loss Function", 0.8)],
        dedup_threshold=0.85,
    )
    # "GD optimization" collapses into the "Gradient Descent" node, so the
    # edge's source resolves there; "Loss Function" becomes a second node.
    assert removed == []
    assert sorted(graph.nodes()) == ["Gradient Descent", "Loss Function"]
    assert graph.edge_count == 1
    assert graph.edges()[0] == {
        "source": "Gradient Descent",
        "target": "Loss Function",
        "confidence": 0.8,
    }
    assert graph.is_dag


def test_add_edge_keeps_highest_confidence():
    g = _make_graph()
    g.add_concepts(["Gradient Descent", "Loss Function"])
    g.add_edge("Gradient Descent", "Loss Function", 0.5)
    g.add_edge("Gradient Descent", "Loss Function", 0.9)
    assert g.edge_count == 1
    assert g.edges()[0]["confidence"] == 0.9


def test_add_edge_skips_self_loop():
    g = _make_graph()
    g.add_concepts(["Loss Function"])
    g.add_edge("Loss Function", "Loss Function", 1.0)
    assert g.edge_count == 0


def test_add_edge_adds_missing_nodes():
    g = _make_graph()
    g.add_edge("A", "B", 0.7)
    assert g.nodes() == ["A", "B"]
    assert g.edge_count == 1


def test_resolve_cycles_removes_lowest_confidence_edge():
    g = _make_graph()
    g.add_concepts(["A", "B", "C"])
    g.add_edge("A", "B", 0.9)
    g.add_edge("B", "C", 0.7)
    g.add_edge("C", "A", 0.2)  # weakest edge in the A->B->C->A cycle

    removed = g.resolve_cycles()
    assert removed == [("C", "A", 0.2)]
    assert g.is_dag
    assert ("C", "A") not in [(e["source"], e["target"]) for e in g.edges()]


def test_resolve_cycles_multiple_cycles():
    g = _make_graph()
    g.add_concepts(["A", "B", "C", "X", "Y", "Z"])
    g.add_edge("A", "B", 0.8)
    g.add_edge("B", "C", 0.6)
    g.add_edge("C", "A", 0.5)
    g.add_edge("X", "Y", 0.9)
    g.add_edge("Y", "Z", 0.9)
    g.add_edge("Z", "X", 0.1)

    removed = g.resolve_cycles()
    assert g.is_dag
    removed_sources = {(a, b) for a, b, _ in removed}
    assert ("C", "A") in removed_sources
    assert ("Z", "X") in removed_sources


def test_acyclic_graph_resolve_returns_nothing():
    g = _make_graph()
    g.add_concepts(["A", "B", "C"])
    g.add_edge("A", "B", 0.9)
    g.add_edge("B", "C", 0.7)
    assert g.resolve_cycles() == []
    assert g.is_dag


def test_topological_order_respects_prerequisites():
    g = _make_graph()
    g.add_concepts(["X", "Y", "Z", "W"])
    g.add_edge("X", "Y", 0.9)
    g.add_edge("Y", "Z", 0.7)
    order = g.topological_order()
    assert order.index("X") < order.index("Y") < order.index("Z")


def test_topological_order_auto_resolves_cycle():
    g = _make_graph()
    g.add_concepts(["A", "B", "C"])
    g.add_edge("A", "B", 0.9)
    g.add_edge("B", "C", 0.7)
    g.add_edge("C", "A", 0.1)
    order = g.topological_order()  # must not raise; cycle broken first
    assert len(order) == 3
    assert g.is_dag


def test_to_dict_shape():
    g = _make_graph()
    g.add_concepts(["A", "B"])
    g.add_edge("A", "B", 0.8)
    data = g.to_dict()
    assert data["nodes"] == ["A", "B"]
    assert data["edges"] == [{"source": "A", "target": "B", "confidence": 0.8}]
    assert data["node_count"] == 2
    assert data["edge_count"] == 1
    assert data["is_dag"] is True
    assert data["topological_order"] == ["A", "B"]


def test_graph_node_and_edge_persistence():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.models import db as models

    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session() as s:
        s.add(models.GraphNode(course_id="ml1", name="Gradient Descent"))
        s.add(models.GraphEdge(course_id="ml1", source="A", target="B", confidence=0.9))
        s.commit()

    with Session() as s:
        nodes = s.query(models.GraphNode).filter_by(course_id="ml1").all()
        edges = s.query(models.GraphEdge).filter_by(course_id="ml1").all()
        assert [n.name for n in nodes] == ["Gradient Descent"]
        assert (edges[0].source, edges[0].target, edges[0].confidence) == ("A", "B", 0.9)