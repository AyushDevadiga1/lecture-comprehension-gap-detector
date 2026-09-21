"""Tests for the interactive DAG renderer (frontend/render.py)."""

from frontend.render import dag_html, lecture_html


def test_dag_html_placeholder_when_no_nodes():
    html = dag_html({"course_id": "ml1", "nodes": [], "edges": [],
                     "node_count": 0, "edge_count": 0, "is_dag": True,
                     "topological_order": []})
    assert html.startswith("<p>No graph")
    assert "Extract concepts + build graph" in html


def test_dag_html_embeds_nodes_edges_and_loads_vis_from_cdn():
    graph = {
        "course_id": "ml1",
        "nodes": ["A", "B", "C"],
        "edges": [
            {"source": "A", "target": "B", "confidence": 0.9},
            {"source": "A", "target": "C", "confidence": 0.8,
             "source_method": "transcript",
             "evidence": "to understand C you need A first"},
        ],
        "node_count": 3,
        "edge_count": 2,
        "is_dag": True,
        "topological_order": ["A", "B", "C"],
    }
    html = dag_html(graph)

    # vis-network is fetched from a CDN so the generated page stays tiny
    # (the inlined build was ~700 KB and made the Faculty tab slow to open)
    assert "vis-network" in html
    assert "https://cdnjs.cloudflare.com/ajax/libs/vis-network" in html
    assert len(html) < 60_000
    assert "A" in html and "B" in html and "C" in html
    assert "edge confidence 0.90" in html and "source: classifier" in html
    assert "edge confidence 0.80" in html and "source: transcript" in html
    assert "to understand C you need A first" in html  # verbatim evidence in the tooltip
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


# ------------------------------------------------- lecture timeline & coverage

def test_lecture_html_computes_covered_fraction():
    html = lecture_html(
        segments=[{"idx": 0, "start_s": 0.0, "end_s": 50.0,
                   "text": "intro about the gradient"},
                  {"idx": 1, "start_s": 50.0, "end_s": 100.0,
                   "text": "dropout randomly silences neurons"}],
        concepts=[{"name": "gradient", "start_s": 0.0, "end_s": 55.0},
                  {"name": "dropout", "start_s": 60.0, "end_s": 100.0}],
        lecture_title="Lec A",
    )
    # covered = 0-55 and 60-100 = 95s of 100s
    assert "95% of the lecture covered" in html
    assert "2 concepts" in html
    assert "2 transcript segments" in html
    assert "dropout randomly silences neurons" in html  # evidence in table
    assert 'width="950.0"' in html  # the green covered band spans 95% of the 1000px bar


def test_lecture_html_renders_empty_lecture():
    html = lecture_html([], [], lecture_title="Empty")
    assert "0 concepts" in html
    assert "0 transcript segments" in html
    assert "0% of the lecture covered" in html


def test_lecture_html_escapes_names():
    html = lecture_html(
        segments=[{"idx": 0, "start_s": 0.0, "end_s": 10.0, "text": "x"}],
        concepts=[{"name": "RNN <b>& friends", "start_s": 0.0, "end_s": 10.0}],
    )
    assert "RNN &lt;b&gt;" in html and "<b>& friends" not in html


def test_dag_html_escapes_tooltip_source_method_and_evidence():
    """SECURITY_AUDIT #24: pyvis renders tooltips as HTML, so attacker-written
    source_method/evidence must not inject markup."""
    graph = {
        "course_id": "ml1",
        "nodes": ["A", "B"],
        "edges": [{
            "source": "A", "target": "B", "confidence": 0.9,
            "source_method": "<img src=x onerror=alert(1)>",
            "evidence": "</title><script>alert(1)</script>",
        }],
        "node_count": 2, "edge_count": 1, "is_dag": True,
        "topological_order": ["A", "B"],
    }
    html = dag_html(graph)
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<script>alert(1)</script>" not in html
    # pyvis JSON-escapes the '&' of the HTML entities as \u0026
    assert "u0026lt;img" in html and "u0026lt;script" in html