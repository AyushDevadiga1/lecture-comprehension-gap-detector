"""Frontend render helpers — importable without Streamlit.

``dag_html()`` turns a course-graph payload (GET /courses/{id}/graph) into
interactive HTML (pyvis + vis-network loaded from a CDN) that the Streamlit
Faculty tab embeds via ``st.components.v1.html``. The CDN build keeps the
generated page itself to a few KB (the inlined vis.js was ~700 KB and made
the tab feel slow to open).

``lecture_html()`` turns a lecture-detail payload (GET /lectures/{id},
segments + concepts) into a static SVG timeline + coverage table: "how much
of the lecture is actually covered by extracted concepts" — the insight the
DAG and quiz both lean on.
"""

import html as _html


def lecture_html(
    segments: list,
    concepts: list,
    lecture_title: str = "",
    *,
    width: int = 1000,
) -> str:
    """Render a lecture's spoken timeline + concept coverage as HTML.

    Args:
        segments: [{idx, start_s, end_s, text}, ...] — the transcript.
        concepts: [{name, start_s, end_s}, ...] — extracted concept windows.
        lecture_title: shown as the header if provided.

    Visual: a grey duration bar with transcript ticks, green "covered" windows
    (union of concept time-spans), then one coloured band per concept in taught
    order. Below, a coverage table lists every concept with its time window,
    transcript support, and the exact sentence used as quiz-answer evidence.

    Self-contained static HTML (no JS, no CDN) so it renders everywhere and
    costs nothing to embed.
    """
    esc = _html.escape
    segments = segments or []
    concepts = concepts or []

    duration = 1.0
    for s in segments:
        duration = max(duration, float(s.get("end_s", 0)))
    for c in concepts:
        for key in ("end_s", "start_s"):
            try:
                duration = max(duration, float(c.get(key, 0) or 0))
            except (TypeError, ValueError):
                pass

    def x(t):
        return (float(t) / duration) * width

    # transcript ticks under the baseline
    ticks = "\n".join(
        '<rect x="%.1f" y="42" width="2" height="6" fill="#cbd5e1"/>'
        % x(s["start_s"])
        for s in segments
    )

    # union of concept windows = "covered" time
    spans = []
    for c in concepts:
        try:
            a = float(c.get("start_s", 0) or 0)
            b = float(c.get("end_s", 0) or a)
        except (TypeError, ValueError):
            continue
        spans.append((max(a, 0.0), max(b, a)))
    covered = float(sum(end - start for start, end in _merge(spans)))
    coverage = covered / duration

    bands = []
    taught = 0
    for c in concepts:
        name = c.get("name", "?")
        try:
            a = float(c.get("start_s", 0) or 0)
            b = float(c.get("end_s", 0) or a)
        except (TypeError, ValueError):
            continue
        fraction = taught / max(len(concepts) - 1, 1)
        r = int(20 + 226 * fraction)
        g = int(184 - 74 * fraction)
        bcol = int(156 - 30 * fraction)
        color = "#%02x%02x%02x" % (r, g, bcol)
        top = 58 + 26 * taught
        y_label = top + 15
        bands.append(
            '<rect x="%.1f" y="%d" width="%.1f" height="14" rx="3" fill="%s">'
            "<title>%s — %.1fs–%.1fs</title></rect>"
            '<text x="%d" y="%d" font-family="Arial" font-size="11" '
            'fill="#1e293b">%s</text>'
            % (
                x(a),
                top,
                max(x(b) - x(a), 2),
                color,
                esc(name),
                a,
                b,
                int(x(a)) + 6,
                y_label,
                esc(name),
            )
        )
        taught += 1

    rows = []
    for i, c in enumerate(concepts, 1):
        name = c.get("name", "?")
        try:
            a = float(c.get("start_s", 0) or 0)
            b = float(c.get("end_s", 0) or a)
            window = "%.1f – %.1fs" % (a, b)
        except (TypeError, ValueError):
            window = "—"
        support = _support_sentence(name, segments)
        rows.append(
            "<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (i, esc(name), window, esc(support or "—"))
        )

    return """
<div style="font-family: Arial, sans-serif; max-width: 1000px;">
  <h5 style="margin:0;">%s</h5>
  <p style="margin:2px 0 8px; color:#475569; font-size:13px;">
    %d concepts · %d transcript segments · <b>%.0f%% of the lecture covered</b>
    by extracted concepts (%.0fs of %.0fs).</p>
  <svg viewBox="0 0 %d %d" width="100%%" height="%d" role="img">
    <rect x="0" y="40" width="%d" height="10" rx="5" fill="#e2e8f0"/>
    %s
    <rect x="0" y="40" width="%.1f" height="10" rx="5" fill="#10b981" opacity="0.65">
      <title>covered: %.1fs</title></rect>
    %s
    <text x="0" y="78" font-family="Arial" font-size="11" fill="#64748b">0s</text>
    <text x="%d" y="78" font-family="Arial" font-size="11" fill="#64748b">%.0fs</text>
  </svg>
  <table style="border-collapse:collapse; width:100%%; margin-top:10px;
                font-size:12.5px;">
    <tr style="text-align:left; color:#475569;">
      <th>#</th><th>Concept</th><th>Window</th><th>Quiz-answer evidence (spoken sentence)</th>
    </tr>
    %s
  </table>
</div>
""" % (
        esc(lecture_title),
        len(concepts),
        len(segments),
        coverage * 100,
        covered,
        duration,
        width,
        78 + 27 * taught,
        78 + 27 * taught,
        width,
        ticks,
        max(x(covered), 1),
        covered,
        "\n".join(bands),
        width - 40,
        duration,
        "\n".join(rows),
    )


def _merge(spans):
    """Merge overlapping time spans into a sorted list of covered ranges."""
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _support_sentence(concept: str, segments: list):
    """Shortest transcript segment mentioning the concept (semantic probe)."""
    best = None
    for seg in segments:
        text = " ".join(str(seg.get("text", "")).split())
        if concept.lower() in text.lower():
            if best is None or len(text) < len(best):
                best = text
    return (best or "")[:160]


def dag_html(graph: dict) -> str:
    """Render a course graph dict as self-contained interactive HTML.

    Expected payload shape (matching ``CourseGraphOut``):
        {course_id, nodes: [name...], edges: [{source, target, confidence}],
         node_count, edge_count, is_dag, topological_order}

    Layout: hierarchical top-down, prerequisites above dependents (mirrors the
    topological learner order). Node tooltip = learner-order position; edge
    tooltip = confidence + where the link came from (spoken transcript vs
    classifier) + the verbatim evidence sentence when one exists. Empty graphs
    return a short placeholder message instead of an empty canvas.
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
        cdn_resources="remote",
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
        method = edge.get("source_method", "classifier")
        tip = "edge confidence %.2f · source: %s" % (conf, method)
        evidence = (edge.get("evidence") or "").strip()
        if evidence:
            tip += "<br/>evidence: %s" % _html.escape(evidence[:300])
        net.add_edge(
            edge["source"],
            edge["target"],
            title=tip,
        )

    return net.generate_html()