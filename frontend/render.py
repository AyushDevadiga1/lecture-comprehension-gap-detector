"""Frontend render helpers — importable without Streamlit.

``dag_html()`` turns a course-graph payload (GET /courses/{id}/graph) into a
self-contained interactive HTML DAG (pyvis, vis.js inlined) that the Streamlit
Faculty tab embeds via ``st.components.v1.html``.
"""


def dag_html(graph: dict) -> str:
    """Render a course graph dict as self-contained interactive HTML.

    Expected payload shape (matching ``CourseGraphOut``):
        {course_id, nodes: [name...], edges: [{source, target, confidence}],
         node_count, edge_count, is_dag, topological_order}

    Layout: hierarchical top-down, prerequisites above dependents (mirrors the
    topological learner order). Node tooltip = learner-order position; edge
    tooltip = prerequisite-classifier confidence. Empty graphs return a short
    placeholder message instead of an empty canvas.
    """
    nodes = graph.get("nodes") or []
    if not nodes:
        return (
            "<p>No graph yet &mdash; run &lsquo;Extract concepts + build graph&rsquo; "
            "from the Student tab, then reload this view.</p>"
        )

    from pyvis.network import Network

    order = graph.get("topological_order") or list(nodes)
    n = max(len(order), 1)
    rank = {name: i for i, name in enumerate(order)}

    net = Network(
        height="720px",
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        cdn_resources="in_line",
    )
    net.set_options(
        """
var options = {
  "layout": {
    "hierarchical": {
      "enabled": true,
      "direction": "UD",
      "sortMethod": "directed",
      "levelSeparation": 190,
      "nodeSpacing": 130
    }
  },
  "interaction": {
    "hover": true,
    "tooltip": false,
    "navigationButtons": true,
    "keyboard": true
  },
  "physics": { "enabled": false },
  "edges": {
    "arrows": { "to": { "enabled": true, "scaleFactor": 0.85 } },
    "smooth": { "enabled": false },
    "color": { "color": "#94a3b8" }
  },
  "nodes": {
    "font": { "face": "Arial", "size": 13, "color": "#1e293b" },
    "borderWidth": 1,
    "shape": "dot"
  }
}
"""
    )
    for name in nodes:
        pos = rank.get(name, n - 1)
        frac = pos / max(n - 1, 1)
        # teal (early, should-learn-first) -> coral (late) colour ramp
        r = int(20 + 226 * frac)
        g = int(184 - 74 * frac)
        b = int(156 - 30 * frac)
        color = "#%02x%02x%02x" % (r, g, b)
        net.add_node(
            name,
            label=name,
            title="%s<br/>learner order #%d/%d" % (name, pos + 1, n),
            color={"background": color, "border": "#334155"},
        )
    for edge in graph.get("edges") or []:
        conf = edge.get("confidence", 1.0)
        net.add_edge(
            edge["source"],
            edge["target"],
            title="prerequisite classifier confidence %.2f" % conf,
        )

    return net.generate_html()