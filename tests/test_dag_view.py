"""DAG view: containment, stable per-node colour, zoom, edge-type filtering.

Reported as: the graph broke the page layout and forced a horizontal scroll
across the whole dashboard; nodes wanted distinct colours with contrasting
labels; and the view needed to be more flexible to work with.
"""

import re

import pytest

from frontend import render


G = {
    "course_id": "ml", "is_dag": True,
    "nodes": ["Conditional Expectation", "Bayes' Rule", "HAVING", "update",
              "Architecture of GRU"],
    "edges": [
        {"source": "Conditional Expectation", "target": "Bayes' Rule",
         "confidence": 0.9, "source_method": "transcript", "evidence": "so then"},
        {"source": "HAVING", "target": "update", "confidence": 0.5,
         "source_method": "classifier"},
        {"source": "update", "target": "Architecture of GRU", "confidence": 0.7,
         "source_method": "classifier"},
    ],
    "node_count": 5, "edge_count": 3,
    "topological_order": ["Conditional Expectation", "HAVING", "update",
                          "Architecture of GRU", "Bayes' Rule"],
}


def _div_style(svg):
    m = re.search(r'<div style="([^"]*)"', svg)
    return m.group(1) if m else ""


# ------------------------------------------------------------- containment

def test_graph_is_wrapped_in_a_scrollable_container():
    svg = render.dag_svg(G, max_nodes=10)
    style = _div_style(svg)
    assert style, "the SVG must be wrapped so it cannot stretch the page"
    assert "overflow:auto" in style
    assert "max-height" in style


def test_container_scrolls_rather_than_widening_the_page():
    """The old bare <svg width=...> forced a page-wide horizontal scrollbar."""
    style = _div_style(render.dag_svg(G, max_nodes=10))
    assert "overflow:auto" in style
    # and the svg is inside that div, not a sibling of it
    svg = render.dag_svg(G, max_nodes=10)
    assert svg.index("<div") < svg.index("<svg")
    assert svg.rindex("</svg>") < svg.index("</div>")


def test_svg_keeps_a_viewbox_so_zoom_scales_rather_than_reflows():
    assert "viewBox=" in render.dag_svg(G, max_nodes=10)


# ------------------------------------------------------------------ colour

def test_node_colours_are_stable_across_calls():
    """Random-per-render would make the whole graph flicker on every rerun."""
    assert render.node_colors("Covariance") == render.node_colors("Covariance")


def test_node_colours_differ_between_nodes():
    names = ["Covariance", "Independence", "HAVING", "update", "Bayes' Rule",
             "Conditional Expectation", "Derangement", "Expectation"]
    fills = {render.node_colors(n)[0] for n in names}
    assert len(fills) == len(names), f"expected distinct fills, got {fills}"


def test_node_text_contrasts_with_its_fill():
    """Label colour must be a dark shade of the same hue, never the fill."""
    for n in ["Covariance", "HAVING", "update", "Bayes' Rule",
              "A Very Long Concept Name Indeed"]:
        fill, ink = render.node_colors(n)
        assert fill != ink
        assert _luminance(ink) < _luminance(fill), n
        # strong separation, comfortably readable
        assert (_luminance(fill) - _luminance(ink)) > 0.35, n


def _luminance(hex_colour):
    r = int(hex_colour[1:3], 16) / 255
    g = int(hex_colour[3:5], 16) / 255
    b = int(hex_colour[5:7], 16) / 255

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def test_svg_uses_the_per_node_colour_for_fill_and_label():
    svg = render.dag_svg(G, max_nodes=10)
    # default mode is learner order, so the fill must come from the rank
    fill, ink = render.node_colors("Conditional Expectation", 0,
                                   len(G["topological_order"]), mode="order")
    assert f'fill="{fill}"' in svg
    assert f'fill="{ink}"' in svg
    # the label is drawn in the dark ink, not the pastel fill
    assert f'font-weight="600" fill="{ink}"' in svg


# -------------------------------------------------------------------- zoom

def test_zoom_scales_the_rendered_size():
    def width(z):
        m = re.search(r'<svg[^>]*\swidth="(\d+)"', render.dag_svg(G, max_nodes=10, zoom=z))
        return int(m.group(1))
    assert width(2.0) > width(1.0) > width(0.5)


def test_zoom_is_clamped_to_a_sane_range():
    def width(z):
        m = re.search(r'<svg[^>]*\swidth="(\d+)"', render.dag_svg(G, max_nodes=10, zoom=z))
        return int(m.group(1))
    assert width(99) == width(3.0)
    assert width(0.01) == width(0.5)


def test_junk_zoom_falls_back_to_one():
    m = re.search(r'<svg[^>]*\swidth="(\d+)"',
                  render.dag_svg(G, max_nodes=10, zoom="nonsense"))
    one = re.search(r'<svg[^>]*\swidth="(\d+)"',
                    render.dag_svg(G, max_nodes=10, zoom=1.0))
    assert m.group(1) == one.group(1)


def test_container_height_is_configurable():
    assert "max-height:400px" in _div_style(render.dag_svg(G, max_nodes=10,
                                                           max_height=400))


# ----------------------------------------------------------- edge filtering

def test_edge_filter_by_source_method():
    both = render.dag_svg(G, max_nodes=10).count("marker-end")
    only_cls = render.dag_svg(G, max_nodes=10,
                              methods=["classifier"]).count("marker-end")
    only_tr = render.dag_svg(G, max_nodes=10,
                             methods=["transcript"]).count("marker-end")
    assert both == 3
    assert only_cls == 2
    assert only_tr == 1


def test_empty_method_list_means_show_everything():
    assert (render.dag_svg(G, max_nodes=10, methods=[]).count("marker-end")
            == 3)


def test_filter_that_matches_nothing_explains_itself():
    """Selecting an edge type with no matching link must not look broken."""
    out = render.dag_svg(G, max_nodes=10, methods=["classifier+llm"])
    assert "No links of the selected type" in out


def test_no_spurious_empty_warning_when_all_types_shown():
    assert "No links of the selected type" not in render.dag_svg(G, max_nodes=10)


# ---------------------------------------------------------- learner order

def test_every_node_carries_its_learner_order_badge():
    """The graph's whole purpose is 'what order do I study this in', so the
    order has to be readable on the graph, not only in a side list."""
    svg = render.dag_svg(G, max_nodes=10)
    # one small dark badge per node
    assert svg.count('rx="5" fill="') >= len(G["nodes"])
    # rank 1 is drawn (Bayes' Rule is first in the order)
    assert ">1<" in svg


def test_badges_use_the_topological_order_not_an_arbitrary_index():
    g = dict(G, nodes=["A", "B", "C"],
             edges=[{"source": "A", "target": "B", "confidence": 0.9},
                    {"source": "B", "target": "C", "confidence": 0.9}],
             node_count=3, edge_count=2, topological_order=["A", "B", "C"])
    svg = render.dag_svg(g, max_nodes=10)
    # A=1, B=2, C=3 -> the badge texts appear in that order in the document
    assert svg.index(">1<") < svg.index(">2<") < svg.index(">3<")


def test_legend_explains_the_badge_and_the_row_direction():
    svg = render.dag_svg(G, max_nodes=10)
    assert "Badge = learner-order position" in svg
    assert "study first" in svg
    assert "Showing 5 of 5 concepts" in svg


def test_legend_reports_how_much_of_the_graph_is_shown():
    g = {"nodes": [f"Concept Number {i} Has A Long Name" for i in range(6)],
         "edges": [], "node_count": 6, "edge_count": 0, "is_dag": True,
         "topological_order": []}
    assert "Showing 2 of 6 concepts" in render.dag_svg(g, max_nodes=2)


def test_missing_topological_order_falls_back_rather_than_breaking():
    """A payload with no topological_order still renders, falling back to the
    shown-node order, so every node keeps a rank badge."""
    g = dict(G, nodes=["A", "B"], edges=[], node_count=2, edge_count=0,
             topological_order=None)
    svg = render.dag_svg(g, max_nodes=10)
    assert "<svg" in svg
    assert ">1<" in svg and ">2<" in svg
    assert "Badge = learner-order position" in svg


# ------------------------------------------------------- regression guards

def test_still_dependency_free_after_the_container_change():
    svg = render.dag_svg(G, max_nodes=10)
    assert "<script" not in svg.lower()
    assert "<iframe" not in svg.lower()
    assert not re.findall(r'https?://(?!www\.w3\.org)', svg)
    assert "node_modules" not in svg


def test_still_escapes_hostile_content_inside_the_container():
    g = dict(G, nodes=["<script>alert(1)</script>", "ok"], edges=[],
             node_count=2, edge_count=0, topological_order=["ok", "ok"])
    svg = render.dag_svg(g, max_nodes=10)
    assert "<script>alert" not in svg
    assert "&lt;script&gt;" in svg


def test_hidden_nodes_note_still_present():
    g = {"nodes": [f"Concept Number {i} Has A Long Name" for i in range(6)],
         "edges": [], "node_count": 6, "edge_count": 0, "is_dag": True,
         "topological_order": []}
    assert "Hiding" in render.dag_svg(g, max_nodes=2)
