"""Tests for the interactive DAG renderer (frontend/render.py)."""

from frontend.render import dag_html


def test_dag_html_placeholder_when_no_nodes():
    html = dag_html({"course_id": "ml1", "nodes": [], "edges": [],
                     "node_count": 0, "edge_count": 0, "is_dag": True,
                     "topological_order": []})
    assert html.startswith("<p>No graph")
    assert "Extract concepts + build graph" in html


def test_dag_html_embeds_nodes_edges_and_is_self_contained():
    graph = {
        "course_id": "ml1",
        "nodes": ["A", "B", "C"],
        "edges": [
            {"source": "A", "target": "B", "confidence": 0.9},
            {"source": "A", "target": "C", "confidence": 0.8},
        ],
        "node_count": 3,
        "edge_count": 2,
        "is_dag": True,
        "topological_order": ["A", "B", "C"],
    }
    html = dag_html(graph)

    assert "vis-network" in html
    assert "<script src=" not in html  # vis.js inlined, no CDN/external lookup
    assert "A" in html and "B" in html and "C" in html
    assert "prerequisite classifier confidence 0.90" in html
    assert "learner order #1/3" in html
    assert "hierarchical" in html and '"direction": "UD"' in html


def test_dag_html_unicode_concept_names_survive():
    graph = {
        "course_id": "ml1",
        "nodes": ["Gated Recurrent Unit \uff5c Deep Learning", "RNN"],
        "edges": [{"source": "Gated Recurrent Unit \uff5c Deep Learning",
                   "target": "RNN", "confidence": 0.99}],
        "node_count": 2, "edge_count": 1, "is_dag": True,
        "topological_order": ["Gated Recurrent Unit \uff5c Deep Learning", "RNN"],
    }
    html = dag_html(graph)
    assert "\\uff5c" in html  # pyvis JSON-escapes the fullwidth bar; browser decodes it