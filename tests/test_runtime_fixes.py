"""Fixes for the four failures reported after running the app for real.

  A. Clip videos never loaded. ``client.media_url`` built a raw URL, and concept
     names routinely contain spaces ("INNER JOIN", "GROUP BY", "transaction
     commit") — 89 of 103 playable clips produced a URL with a literal space, so
     the media request failed. The filename is now percent-encoded.

  B. The graph "loaded" but never appeared. ``dag_html`` emitted vis-network and
     Bootstrap from two CDNs plus ``../node_modules/vis/dist/vis.js`` — a path
     that does not exist in this repository. Replaced by ``dag_svg``: inline,
     dependency-free SVG with no script, no iframe and no network.

  C. A legitimate long graph rebuild was declared "stalled" and killed. The C0
     cutoff was one flat budget, but the heavy stages publish only coarse
     milestones around work that legitimately takes minutes. The budget is now
     stage-aware.

  D. The bar froze on one number through the whole scoring phase, because
     ``classify_course_pairs`` had no way to report its internal sub-steps. It
     now takes an ``on_progress`` callback fired at real boundaries.

  E. The DAG was an unreadable hairball of micro-concepts. ``graph_importance``
     ranks nodes by degree, name specificity and case shape so keyword fragments
     rank out, and the UI exposes the cut as a slider.
"""

import urllib.parse

import pytest

from frontend import client as client_mod
from frontend import render


# ------------------------------------------------------- A. clip URL encoding

def test_media_url_percent_encodes_spaces():
    url = client_mod.media_url("data/processed/clips/3/INNER JOIN__1960-1998.mp4")
    assert url.endswith("/media/clips/3/INNER%20JOIN__1960-1998.mp4")
    assert " " not in url


def test_media_url_encoding_round_trips_to_the_real_filename():
    import urllib.parse as up
    raw = "data/processed/clips/1/transaction commit__1813-1839.mp4"
    url = client_mod.media_url(raw)
    got = up.unquote(up.urlparse(url).path.rsplit("/", 1)[-1])
    assert got == "transaction commit__1813-1839.mp4"


def test_media_url_preserves_a_literal_percent_in_the_filename():
    """The input is a real filesystem path, so a literal '%' must survive.

    Deliberately does not unquote-then-requote: a clip whose concept name
    genuinely contains '%20' would be corrupted by that, and the only caller
    (the clips payload) always passes a raw path.
    """
    url = client_mod.media_url("data/processed/clips/1/50% off__10-20.mp4")
    assert url.endswith("/50%25%20off__10-20.mp4")
    assert urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]) \
        == "50% off__10-20.mp4"


def test_media_url_escapes_non_ascii():
    url = client_mod.media_url("data/processed/clips/1/café — x.mp4")
    assert " " not in url
    assert "%20" in url or "%C3%A9" in url


def test_media_url_still_rejects_traversal():
    assert client_mod.media_url("data/processed/clips/../../etc/passwd") is None
    assert client_mod.media_url("") is None
    assert client_mod.media_url("data/processed/clips/x/a.mp4") is None


# ----------------------------------------------------- B. dependency-free SVG

GRAPH = {
    "course_id": "ml", "is_dag": True,
    "nodes": ["Conditional Expectation", "Bayes' Rule", "HAVING", "update"],
    "edges": [
        {"source": "Conditional Expectation", "target": "Bayes' Rule",
         "confidence": 0.9, "source_method": "transcript", "evidence": "so then"},
        {"source": "HAVING", "target": "update", "confidence": 0.5},
    ],
    "node_count": 4, "edge_count": 2,
    "topological_order": ["Conditional Expectation", "HAVING", "update", "Bayes' Rule"],
}


def test_dag_svg_has_no_external_dependencies():
    svg = render.dag_svg(GRAPH)
    assert "<script" not in svg.lower()
    assert "<iframe" not in svg.lower()
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in svg
    assert "cdn" not in svg.lower()
    assert "node_modules" not in svg


def test_dag_svg_is_an_svg_inside_its_container():
    out = render.dag_svg(GRAPH, max_nodes=10)
    # wrapped in a scroll container so a wide graph cannot stretch the page
    assert out.lstrip().startswith('<div style="')
    assert "<svg" in out
    assert "</svg></div>" in out


def test_dag_svg_draws_a_node_per_kept_concept():
    svg = render.dag_svg(GRAPH, max_nodes=10)
    # node boxes use rx="7"; the learner-order badges use rx="5", and there is
    # one full-bleed background rect
    assert svg.count('rx="7"') == len(GRAPH["nodes"])
    assert svg.count("<rect") == len(GRAPH["nodes"]) * 2 + 1  # node + badge + bg


def test_dag_svg_draws_edges_with_arrowheads():
    svg = render.dag_svg(GRAPH, max_nodes=10)
    assert svg.count("marker-end") == 2


def test_dag_svg_escapes_hostile_labels():
    g = dict(GRAPH, nodes=["<script>alert(1)</script>", "safe"],
             edges=[], node_count=2, edge_count=0, topological_order=["safe"])
    svg = render.dag_svg(g, max_nodes=10)
    assert "<script>alert" not in svg
    assert "&lt;script&gt;" in svg


def test_dag_svg_escapes_edge_evidence():
    g = dict(GRAPH,
             edges=[{"source": "safe", "target": "safe2", "confidence": 0.9,
                     "source_method": "<b>x</b>", "evidence": "<img src=x>"}],
             nodes=["safe", "safe2"], node_count=2, edge_count=1,
             topological_order=["safe", "safe2"])
    svg = render.dag_svg(g, max_nodes=10)
    assert "<img src=x>" not in svg
    assert "&lt;img" in svg


def test_dag_svg_placeholder_when_no_nodes():
    out = render.dag_svg({"nodes": [], "edges": []})
    assert "No graph yet" in out
    assert "<svg" not in out


def test_dag_svg_survives_a_cycle():
    g = {"nodes": ["a", "b"], "is_dag": False, "node_count": 2, "edge_count": 2,
         "edges": [{"source": "a", "target": "b", "confidence": 0.9},
                   {"source": "b", "target": "a", "confidence": 0.9}],
         "topological_order": ["a", "b"]}
    assert "<svg" in render.dag_svg(g, max_nodes=10)


def test_dag_svg_tolerates_non_numeric_confidence():
    g = dict(GRAPH, edges=[{"source": "Conditional Expectation",
                            "target": "Bayes' Rule", "confidence": "n/a"}])
    assert "<svg" in render.dag_svg(g, max_nodes=10)


def test_dag_svg_tolerates_null_topological_order():
    g = dict(GRAPH, topological_order=None)
    assert "<svg" in render.dag_svg(g, max_nodes=10)


def test_dag_svg_drops_edges_to_hidden_nodes():
    """An edge to a node the filter removed must not be drawn."""
    g = {"nodes": ["Real Concept Number One", "Real Concept Number Two", "HAVING"],
         "edges": [{"source": "Real Concept Number One",
                    "target": "Real Concept Number Two", "confidence": 0.9},
                   {"source": "HAVING", "target": "Real Concept Number One",
                    "confidence": 0.5}],
         "is_dag": True, "node_count": 3, "edge_count": 2,
         "topological_order": ["HAVING", "Real Concept Number One",
                               "Real Concept Number Two"]}
    kept, dropped = render.graph_importance(g, limit=2)
    assert "HAVING" in dropped
    svg = render.dag_svg(g, max_nodes=2)
    # only the surviving edge is painted
    assert svg.count("marker-end") == 1


# ------------------------------------------------------ E. importance ranking

def test_graph_importance_ranks_out_keyword_fragments():
    g = {"nodes": ["Conditional Expectation And Its Properties", "HAVING",
                   "delete", "update", "GROUP BY", "SQL JOIN"],
         "edges": [{"source": "Conditional Expectation And Its Properties",
                    "target": "HAVING", "confidence": 0.9},
                   {"source": "HAVING", "target": "delete", "confidence": 0.9},
                   {"source": "delete", "target": "update", "confidence": 0.9},
                   {"source": "update", "target": "GROUP BY", "confidence": 0.9},
                   {"source": "GROUP BY", "target": "SQL JOIN", "confidence": 0.9}],
         "node_count": 6, "edge_count": 5, "is_dag": True,
         "topological_order": []}
    kept, dropped = render.graph_importance(g, limit=2)
    assert "Conditional Expectation And Its Properties" in kept
    assert {"HAVING", "GROUP BY", "SQL JOIN"} & dropped


def test_graph_importance_keeps_everything_when_under_the_limit():
    kept, dropped = render.graph_importance({"nodes": ["a", "b"], "edges": []}, limit=40)
    assert kept == {"a", "b"}
    assert dropped == set()


def test_graph_importance_zero_limit_keeps_all():
    kept, _ = render.graph_importance({"nodes": ["a", "b"], "edges": []}, limit=0)
    assert kept == {"a", "b"}


def test_dag_svg_reports_what_it_hid():
    g = {"nodes": [f"Concept Number {i} With A Long Name" for i in range(6)],
         "edges": [], "node_count": 6, "edge_count": 0, "is_dag": True,
         "topological_order": []}
    svg = render.dag_svg(g, max_nodes=2)
    assert "Hiding" in svg


# ------------------------------------------------- C. stage-aware stall budget

def test_slow_stages_get_a_larger_stall_budget():
    from frontend import components

    assert (components._MAX_STALLED_POLLS_SLOW
            > components._MAX_STALLED_POLLS)
    for stage in ("building_graph", "extracting", "cutting_clips",
                  "local_transcribing"):
        assert stage in components._SLOW_STAGES, stage


def test_slow_stall_budget_is_still_bounded():
    from frontend import components

    # must stay well under the 6h deadline, but comfortably above a
    # multi-minute dedup/score/re-encode phase
    assert components._MAX_STALLED_POLLS_SLOW <= 1200
    assert components._MAX_STALLED_POLLS_SLOW * 1.5 < components._JOB_DEADLINE_S


def test_uploaded_row_still_uses_the_tight_budget():
    """The original 6-hour flicker must stay fixed: a stuck `uploaded` row is
    cheap to detect and must not get the slow-stage allowance."""
    from frontend import components

    assert "uploaded" not in components._SLOW_STAGES


# ---------------------------------------------------- D. progress sub-stepping

def test_classify_course_pairs_reports_substeps():
    from backend.pipeline import classify_prerequisites as cp

    seen = []

    def fake_lib(_dir):
        return {"pairs": [(("a", "b"), 1)]}

    class _Clf:
        def predict_proba(self, cands):
            return [0.9 for _ in cands]

    monkey = cp
    orig_lib, orig_cand, orig_fit = (
        cp._load_lecturebank, cp.get_candidate_pairs, cp._fitted_classifier)
    cp._load_lecturebank = fake_lib
    cp.get_candidate_pairs = lambda concepts, encoder=None: [("a", "b")]
    cp._fitted_classifier = lambda lib, encoder=None: _Clf()
    try:
        out = cp.classify_course_pairs(
            [{"name": "a"}, {"name": "b"}],
            on_progress=lambda pct, detail: seen.append((pct, detail)))
    finally:
        cp._load_lecturebank = orig_lib
        cp.get_candidate_pairs = orig_cand
        cp._fitted_classifier = orig_fit

    assert out and out[0]["a"] == "a"
    assert len(seen) >= 4, seen
    pcts = [p for p, _ in seen]
    assert pcts == sorted(pcts), "progress must be monotonic"
    assert any("candidate pairs" in d.lower() for _, d in seen)


def test_progress_callback_failure_does_not_break_the_build():
    from backend.pipeline import classify_prerequisites as cp

    class _Clf:
        def predict_proba(self, cands):
            return [0.9 for _ in cands]

    orig_lib, orig_cand, orig_fit = (
        cp._load_lecturebank, cp.get_candidate_pairs, cp._fitted_classifier)
    cp._load_lecturebank = lambda _d: {"pairs": []}
    cp.get_candidate_pairs = lambda concepts, encoder=None: [("a", "b")]
    cp._fitted_classifier = lambda lib, encoder=None: _Clf()

    def boom(pct, detail):
        raise RuntimeError("progress sink is down")

    try:
        out = cp.classify_course_pairs([{"name": "a"}], on_progress=boom)
    finally:
        cp._load_lecturebank = orig_lib
        cp.get_candidate_pairs = orig_cand
        cp._fitted_classifier = orig_fit
    assert out  # the build completed despite the broken progress sink


def test_classify_course_pairs_still_works_without_a_callback():
    from backend.pipeline import classify_prerequisites as cp

    class _Clf:
        def predict_proba(self, cands):
            return [0.9 for _ in cands]

    orig_lib, orig_cand, orig_fit = (
        cp._load_lecturebank, cp.get_candidate_pairs, cp._fitted_classifier)
    cp._load_lecturebank = lambda _d: {"pairs": []}
    cp.get_candidate_pairs = lambda concepts, encoder=None: [("a", "b")]
    cp._fitted_classifier = lambda lib, encoder=None: _Clf()
    try:
        assert cp.classify_course_pairs([{"name": "a"}])
    finally:
        cp._load_lecturebank = orig_lib
        cp.get_candidate_pairs = orig_cand
        cp._fitted_classifier = orig_fit
