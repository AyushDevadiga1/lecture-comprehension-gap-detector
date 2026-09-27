"""Frontend render helpers — importable without Streamlit.

``dag_html()`` turns a course-graph payload (GET /courses/{id}/graph) into
interactive HTML (pyvis + vis-network loaded from a CDN) that the Faculty
dashboard embeds via ``st.iframe``. The CDN build keeps the generated page
itself to a few KB (the inlined vis.js was ~700 KB and made the view feel
slow to open); a missing pyvis degrades to a placeholder instead of a crash.

``lecture_html()`` turns a lecture-detail payload (GET /lectures/{id},
segments + concepts) into a static SVG timeline + coverage table: "how much
of the lecture is actually covered by extracted concepts" — the insight the
DAG and quiz both lean on.
"""

import colorsys
import hashlib
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

    # union of concept windows = "covered" time. Draw one green rect PER merged
    # run (finding A4) so gaps between concept windows are visible and the
    # graphic matches the honest % caption.
    spans = []
    for c in concepts:
        try:
            a = float(c.get("start_s", 0) or 0)
            b = float(c.get("end_s", 0) or a)
        except (TypeError, ValueError):
            continue
        spans.append((max(a, 0.0), max(b, a)))
    merged = _merge(spans)
    covered = float(sum(end - start for start, end in merged))
    coverage = covered / duration
    covered_rects = "\n".join(
        '<rect x="%.1f" y="40" width="%.1f" height="10" rx="2" '
        'fill="#10b981" opacity="0.65">'
        "<title>covered: %.1fs–%.1fs</title></rect>"
        % (x(start), max(x(end) - x(start), 1), start, end)
        for start, end in merged
    )

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
    %s
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
        covered_rects,
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


def _load_pyvis_network():
    """Module-local accessor so tests can inject a failing import (A5)."""
    from pyvis.network import Network  # noqa: F401

    return Network


def _support_sentence(concept: str, segments: list):
    """Shortest transcript segment mentioning the concept (semantic probe)."""
    best = None
    for seg in segments:
        text = " ".join(str(seg.get("text", "")).split())
        if concept.lower() in text.lower():
            if best is None or len(text) < len(best):
                best = text
    return (best or "")[:160]


def graph_importance(graph: dict, limit: int = 40):
    """Rank graph nodes so the important ones survive a readability cut.

    A course DAG can easily hold 100+ nodes, and forcing all of them into one
    view is unreadable in *any* renderer — this is a content problem, not a
    framework one. Concepts like "HAVING", "update" or "GROUP BY" are real rows
    in the graph but are not concepts a learner needs to reason about.

    Score (higher = keep):
      * graph degree — a node with several prerequisite links is load-bearing;
      * name specificity — a multi-word name ("Conditional Expectation") is a
        concept, a single bare token ("update", "filter") usually is not;
      * case shape — ALL-CAPS names are overwhelmingly SQL/keyword fragments.

    Returns ``(kept_names, dropped_names)``.
    """
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    degree: dict = {}
    for e in edges:
        for side in ("source", "target"):
            nm = e.get(side)
            if nm:
                degree[nm] = degree.get(nm, 0) + 1

    def score(name: str) -> float:
        s = float(degree.get(name, 0)) * 1.0
        words = [w for w in str(name).split() if w]
        if len(words) >= 2:
            s += 2.0
        if len(str(name)) >= 18:
            s += 1.0
        letters = [ch for ch in str(name) if ch.isalpha()]
        if letters and all(ch.isupper() for ch in letters):
            s -= 2.5
        if len(str(name)) <= 6:
            s -= 1.0
        return s

    ranked = sorted(nodes, key=lambda n: (-score(n), str(n)))
    if limit and len(ranked) > limit:
        kept = set(ranked[:limit])
        return kept, set(nodes) - kept
    return set(nodes), set()


def node_colors(name: str):
    """Stable per-node fill + a high-contrast label colour.

    "Random" but *deterministic*: the hue is derived from a hash of the node
    name, so a node keeps its colour across reruns. Genuinely random-per-render
    would make the whole graph flicker on every Streamlit rerun, which is
    exactly the kind of churn this view is trying to avoid.

    Fill is a light pastel (lightness 0.74-0.87) and the label is a very dark
    shade of the *same* hue, so text contrast stays strong whatever the hue —
    adjacent nodes still read as distinct because the lightness varies too.
    """
    digest = hashlib.sha256(str(name).encode("utf-8")).digest()
    hue = digest[0] / 255.0
    light = 0.74 + (digest[1] / 255.0) * 0.13
    sat = 0.52 + (digest[2] / 255.0) * 0.20

    def _hex(l, s):
        r, g, b = colorsys.hls_to_rgb(hue, l, s)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

    return _hex(light, sat), _hex(0.20, min(sat + 0.1, 0.95))


def dag_svg(
    graph: dict,
    max_nodes: int = 40,
    width: int = 1180,
    zoom: float = 1.0,
    methods=None,
    max_height: int = 560,
) -> str:
    """Render a course graph as a self-contained, scroll-contained inline SVG.

    Deliberately dependency-free: the previous renderer emitted vis-network and
    Bootstrap from two CDNs plus a ``../node_modules/vis/dist/vis.js`` path that
    does not exist in this repository, so the graph silently failed to render
    whenever the CDN was unreachable. This needs no JavaScript, no iframe, and
    no network at all, which also means it renders inside Streamlit directly.

    The SVG is wrapped in a fixed-height ``overflow:auto`` box so a wide graph
    scrolls *inside* its container instead of stretching the page and forcing a
    horizontal scrollbar for the whole dashboard. ``zoom`` scales the drawing
    via the viewBox, so it costs no script.

    Layout is layered by longest-path depth so prerequisites sit above the
    concepts that depend on them, matching the learner order. ``methods``
    filters edges by ``source_method`` (e.g. only spoken-transcript links).
    """
    nodes = graph.get("nodes") or []
    if not nodes:
        return (
            "<p>No graph yet &mdash; run &lsquo;Extract concepts + build graph&rsquo; "
            "from the Student dashboard, then reload this view.</p>"
        )

    try:
        zoom = float(zoom)
    except (TypeError, ValueError):
        zoom = 1.0
    # clamped to the same 0.5-2.0 range the UI sliders expose
    zoom = min(max(zoom, 0.5), 3.0)

    kept, dropped = graph_importance(graph, limit=max_nodes)
    shown = [n for n in nodes if n in kept]
    shown_set = set(shown)
    all_edges = [
        e for e in (graph.get("edges") or [])
        if e.get("source") in shown_set and e.get("target") in shown_set
    ]
    if methods:
        wanted = {str(m) for m in methods}
        edges = [e for e in all_edges
                 if str(e.get("source_method", "classifier")) in wanted]
    else:
        edges = all_edges

    # longest-path depth per node, restricted to the edges we draw
    depth: dict = {}

    def node_depth(name, seen=None):
        if name in depth:
            return depth[name]
        seen = seen or set()
        if name in seen:            # defensive: the graph claims to be a DAG
            return 0
        seen.add(name)
        parents = [e["source"] for e in edges if e["target"] == name]
        d = 0 if not parents else 1 + max(node_depth(p, seen) for p in parents)
        depth[name] = d
        return d

    for n in shown:
        node_depth(n)

    levels: dict = {}
    for n in shown:
        levels.setdefault(depth[n], []).append(n)
    for items in levels.values():
        items.sort(key=str)

    order = graph.get("topological_order") or shown
    rank = {name: i for i, name in enumerate(order)}

    node_w, node_h, gap_x, gap_y, pad = 168, 34, 18, 58, 20
    widest = max((len(v) for v in levels.values()), default=1)
    row_w = widest * (node_w + gap_x) - gap_x
    height = pad * 2 + max(len(levels), 1) * (node_h + gap_y)
    svg_w = max(width, row_w + pad * 2)

    shown_w = round(svg_w * zoom)
    shown_h = round(height * zoom)

    parts = [
        f'<div style="max-height:{max_height}px;overflow:auto;border:1px solid #e2e8f0;'
        f'border-radius:10px;background:#ffffff;padding:4px">',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{shown_w}" height="{shown_h}" viewBox="0 0 {svg_w} {height}" '
        f'role="img" aria-label="Course prerequisite graph" '
        f'style="display:block">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8"/></marker></defs>',
        f'<rect width="{svg_w}" height="{height}" fill="#ffffff"/>',
    ]

    pos = {}
    for level, items in sorted(levels.items()):
        y = pad + level * (node_h + gap_y)
        total = len(items) * (node_w + gap_x) - gap_x
        x0 = (svg_w - total) / 2
        for i, name in enumerate(items):
            pos[name] = (x0 + i * (node_w + gap_x), y)

    # edges first so nodes paint over them
    for e in edges:
        x1, y1 = pos[e["source"]]
        x2, y2 = pos[e["target"]]
        x1c, y1c = x1 + node_w / 2, y1 + node_h
        x2c, y2c = x2 + node_w / 2, y2
        conf = e.get("confidence", 1.0)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 1.0
        method = _html.escape(str(e.get("source_method", "classifier")))
        tip = f"confidence {conf:.2f} - source: {method}"
        ev = (e.get("evidence") or "").strip()
        if ev:
            tip += f" - evidence: {_html.escape(ev[:300])}"
        parts.append(
            f'<path d="M {x1c:.1f} {y1c:.1f} C {x1c:.1f} {y1c + 22:.1f}, '
            f'{x2c:.1f} {y2c - 22:.1f}, {x2c:.1f} {y2c:.1f}" fill="none" '
            f'stroke="#cbd5e1" stroke-width="1.3" marker-end="url(#arrow)">'
            f'<title>{tip}</title></path>'
        )

    for name, (x, y) in pos.items():
        fill, ink = node_colors(name)
        label = _html.escape(str(name))
        r = rank.get(name)
        shown_n = max(len(order), 1)
        tip = (f"learner order #{r + 1}/{shown_n}" if r is not None
               else "learner order unknown")
        badge = ""
        if r is not None:
            # learner-order badge: the graph is only useful if you can read the
            # order to study in, so it is drawn on the node, not hidden in a list
            badge = (
                f'<rect x="{x:.1f}" y="{y - 8:.1f}" width="21" height="16" rx="5" '
                f'fill="{ink}"/>'
                f'<text x="{x + 10.5:.1f}" y="{y + 4:.1f}" font-size="10" '
                f'font-weight="700" fill="#ffffff" text-anchor="middle">'
                f'{r + 1}</text>'
            )
        parts.append(
            f'<g><title>{_html.escape(tip)}</title>{badge}'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{node_w}" height="{node_h}" '
            f'rx="7" fill="{fill}" stroke="{ink}" stroke-width="1"/>'
            f'<text x="{x + node_w / 2:.1f}" y="{y + node_h / 2 + 4:.1f}" '
            f'font-family="Segoe UI,Arial,sans-serif" font-size="12" '
            f'font-weight="600" fill="{ink}" text-anchor="middle">'
            f'{label[:26]}</text></g>'
        )

    parts.append("</svg></div>")

    # legend: what the badge and the layering mean
    n_shown = len(shown)
    parts.append(
        f'<p style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;'
        f'color:#64748b;margin:6px 2px 0">Badge = position in the learner order '
        f'(1 = study first, of {len(order)} concepts). Each row depends only on '
        f'rows above it, so study top-down. Showing {n_shown} of {len(nodes)} '
        f'concepts.</p>'
    )

    if edges == [] and all_edges:
        parts.append(
            '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;'
            'color:#b45309;margin:6px 2px 0">No links of the selected type connect '
            'the concepts currently shown. Re-enable an edge type, or raise '
            '"Concepts shown" — spoken-transcript links are usually few and often '
            'join nodes the significance filter hides.</p>'
        )
    if dropped:
        names = sorted(str(d) for d in dropped)[:12]
        parts.append(
            f'<p style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;'
            f'color:#64748b;margin:6px 2px 0">Hiding {len(dropped)} '
            f'lower-significance node(s) to keep this readable, e.g. '
            f'{_html.escape(", ".join(names))}. Raise the limit to see them.</p>'
        )
    return "".join(parts)


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
            "from the Student dashboard, then reload this view.</p>"
        )

    # A5: pyvis is a heavy, lazy dependency — a missing/broken install must not
    # traceback the whole Faculty dashboard, just the interactive canvas.
    try:
        Network = _load_pyvis_network()
    except ImportError:
        return (
            "<p>The interactive DAG add-on (pyvis / vis-network) is not "
            "available on this install. Use the learner-order list below "
            "instead.</p>"
        )

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
            title="%s<br/>learner order #%d/%d" % (_html.escape(str(name)), pos + 1, n),
            color={"background": color, "border": "#334155"},
        )
    for edge in graph.get("edges") or []:
        conf = edge.get("confidence", 1.0)
        # SECURITY_AUDIT #24: tooltips are rendered as HTML by pyvis, so every
        # attacker-influenced string must be escaped.
        method = _html.escape(str(edge.get("source_method", "classifier")))
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