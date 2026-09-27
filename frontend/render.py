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

Every colour here comes from :mod:`frontend.theme` (which follows the theme the
app declares). Nothing in this module picks a colour by eye: node labels and
badges get their ink from a measured contrast choice, so they stay legible on
whichever fill a node ends up with.
"""

import hashlib
import html as _html

from frontend import theme


def lecture_html(
    segments: list,
    concepts: list,
    lecture_title: str = "",
    *,
    width: int = 1000,
    base: str = None,
) -> str:
    """Render a lecture's spoken timeline + concept coverage as HTML.

    Args:
        segments: [{idx, start_s, end_s, text}, ...] — the transcript.
        concepts: [{name, start_s, end_s}, ...] — extracted concept windows.
        lecture_title: shown as the header if provided.
        base: theme base override ("dark"/"light"); None = the running app's.

    Visual: a track bar with transcript ticks, green "covered" windows
    (union of concept time-spans), then one coloured band per concept in taught
    order. Below, a coverage table lists every concept with its time window,
    transcript support, and the exact sentence used as quiz-answer evidence.

    Self-contained static HTML (no JS, no CDN) so it renders everywhere and
    costs nothing to embed.
    """
    esc = _html.escape
    pal = theme.palette(base)
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
        '<rect x="%.1f" y="42" width="2" height="6" fill="%s"/>'
        % (x(s["start_s"]), pal.tick)
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
        'fill="%s" opacity="0.75">'
        "<title>covered: %.1fs&ndash;%.1fs</title></rect>"
        % (x(start), max(x(end) - x(start), 1), pal.covered, start, end)
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
        # teal -> coral, the same hue the DAG ramp uses, so a concept reads the
        # same way in the timeline and in the graph
        hue = (175.0 + (8.0 - 175.0) * fraction) / 360.0
        color = theme.node_fill(hue, base=base)
        ink = theme.readable_on(color, base=base)   # never white-on-white
        top = 58 + 26 * taught
        y_label = top + 15
        bands.append(
            '<rect x="%.1f" y="%d" width="%.1f" height="14" rx="3" fill="%s">'
            "<title>%s — %.1fs–%.1fs</title></rect>"
            '<text x="%d" y="%d" font-family="Arial" font-size="11" '
            'fill="%s">%s</text>'
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
                ink,
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
<div style="font-family: Arial, sans-serif; max-width: 1000px; color:%(text)s;">
  <h5 style="margin:0; color:%(text)s;">%(title)s</h5>
  <p style="margin:2px 0 8px; color:%(muted)s; font-size:13px;">
    %(n_concepts)d concepts · %(n_segments)d transcript segments · <b>%(pct).0f%% of the lecture covered</b>
    by extracted concepts (%(covered).0fs of %(duration).0fs).</p>
  <svg viewBox="0 0 %(width)d %(height)d" width="100%%" height="%(height)d" role="img">
    <rect x="0" y="40" width="%(width)d" height="10" rx="5" fill="%(track)s"/>
    %(ticks)s
    %(covered_rects)s
    %(bands)s
    <text x="0" y="78" font-family="Arial" font-size="11" fill="%(muted)s">0s</text>
    <text x="%(label_x)d" y="78" font-family="Arial" font-size="11" fill="%(muted)s">%(duration).0fs</text>
  </svg>
  <table style="border-collapse:collapse; width:100%%; margin-top:10px;
                font-size:12.5px; color:%(text)s;">
    <tr style="text-align:left; color:%(muted)s; background:%(surface_alt)s;">
      <th>#</th><th>Concept</th><th>Window</th><th>Quiz-answer evidence (spoken sentence)</th>
    </tr>
    %(rows)s
  </table>
</div>
""" % dict(
        text=pal.text,
        title=esc(lecture_title),
        n_concepts=len(concepts),
        n_segments=len(segments),
        pct=coverage * 100,
        covered=covered,
        duration=duration,
        width=width,
        height=78 + 27 * taught,
        track=pal.track,
        ticks=ticks,
        covered_rects=covered_rects,
        bands="\n".join(bands),
        label_x=width - 40,
        muted=pal.muted,
        surface_alt=pal.surface_alt,
        rows="\n".join(rows),
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


def node_colors(name: str, rank: int = None, total: int = None,
                mode: str = "order", base: str = None):
    """Return ``(fill, ink)`` for a node.

    Two modes, because they answer different questions:

    * ``mode="order"`` — a teal→coral ramp along the learner sequence, so "what
      do I study first" is visible at a glance.
    * ``mode="identity"`` — a hue hashed from the node *name*, giving every
      concept its own stable colour. The hash is deliberate rather than a random
      draw: genuinely random-per-render would recolour the whole graph on every
      Streamlit rerun.

    Two earlier approaches were replaced rather than tuned. Lerping RGB endpoints
    ran the teal end to ~2.6:1 against its own label, below the 4.5:1 AA floor.
    The fixed-lightness HSL ramp fixed that by keeping a *light* fill and a *dark*
    ink — legible, but on the dark theme every node became a bright slab, and a
    mid-luminance hue could still land below the floor.

    Now the fill follows the theme (a dark tinted block on dark, a light one on
    light) and the ink is chosen by measured contrast rather than by guesswork:
    :func:`theme.readable_on` returns whichever candidate actually reads better,
    so a label is legible on any fill the ramp or hash can produce.
    """
    base = base or theme.current_base()
    if mode == "order" and rank is not None and total and total > 1:
        frac = min(max(rank / float(total - 1), 0.0), 1.0)
        hue = (175.0 + (8.0 - 175.0) * frac) / 360.0   # teal -> coral
        return theme.node_pair(hue, base=base)

    digest = hashlib.sha256(str(name).encode("utf-8")).digest()
    hue = digest[0] / 255.0
    sat = 0.45 + (digest[2] / 255.0) * 0.18
    return theme.node_pair(hue, base=base, sat=sat)


def dag_svg(
    graph: dict,
    max_nodes: int = 40,
    width: int = 1180,
    zoom: float = 1.0,
    methods=None,
    max_height: int = 560,
    color_by: str = "order",
    base: str = None,
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
    ``base`` overrides the theme base; None = the running app's theme.
    """
    pal = theme.palette(base)
    nodes = graph.get("nodes") or []
    if not nodes:
        return (
            f'<div style="background:{pal.graph_bg};color:{pal.text};'
            f'font-family:Segoe UI,Arial,sans-serif">'
            "<p>No graph yet &mdash; run &lsquo;Extract concepts + build graph&rsquo; "
            "from the Student dashboard, then reload this view.</p></div>"
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

    # `resize:vertical` lets the reader drag the frame taller or shorter without
    # any JavaScript - pure CSS, so it costs nothing and cannot break offline.
    parts = [
        f'<div style="max-height:{max_height}px;min-height:180px;overflow:auto;'
        f'resize:vertical;border:1px solid {pal.border};border-radius:10px;'
        f'background:{pal.graph_bg};padding:4px">',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{shown_w}" height="{shown_h}" viewBox="0 0 {svg_w} {height}" '
        f'role="img" aria-label="Course prerequisite graph" '
        f'style="display:block">',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{pal.graph_edge}"/></marker></defs>',
        f'<rect width="{svg_w}" height="{height}" fill="{pal.graph_bg}"/>',
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
            f'stroke="{pal.graph_edge}" stroke-width="1.3" marker-end="url(#arrow)">'
            f'<title>{tip}</title></path>'
        )

    for name, (x, y) in pos.items():
        r_index = rank.get(name)
        fill, ink = node_colors(name, r_index, len(order),
                                mode="order" if color_by == "order" else "identity",
                                base=base)
        label = _html.escape(str(name))
        shown_n = max(len(order), 1)
        tip = (f"learner order #{r_index + 1}/{shown_n}" if r_index is not None
               else "learner order unknown")
        badge = ""
        if r_index is not None:
            # learner-order badge: the graph is only useful if you can read the
            # order to study in, so it is drawn on the node, not hidden in a list
            badge = (
                f'<rect x="{x:.1f}" y="{y - 8:.1f}" width="21" height="16" rx="5" '
                f'fill="{ink}"/>'
                f'<text x="{x + 10.5:.1f}" y="{y + 4:.1f}" font-size="10" '
                f'font-weight="700" fill="{theme.readable_on(ink, base=base)}" '
                f'text-anchor="middle">{r_index + 1}</text>'
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

    if edges == [] and all_edges:
        parts.append(
            '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;'
            f'color:{pal.warn};margin:6px 2px 0">No links of the selected type '
            'connect the concepts currently shown. Re-enable an edge type, or raise '
            '"Concepts shown" &mdash; spoken-transcript links are usually few and often '
            'join nodes the significance filter hides.</p>'
        )
    if dropped:
        names = sorted(str(d) for d in dropped)[:12]
        parts.append(
            f'<p style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;'
            f'color:{pal.muted};margin:6px 2px 0">Hiding {len(dropped)} '
            f'lower-significance node(s) to keep this readable, e.g. '
            f'{_html.escape(", ".join(names))}. Raise the limit to see them.</p>'
        )

    parts.append(_legend(color_by, len(shown), len(nodes), len(order), base=base))
    return "".join(parts)


def _legend(color_by, n_shown, n_total, n_order, base: str = None) -> str:
    """A visible key for the colour scheme, plus how much of the graph is shown."""
    pal = theme.palette(base)
    if color_by == "order":
        swatches = "".join(
            f'<span style="display:inline-block;width:26px;height:11px;'
            f'background:{node_colors("k", i, 11, mode="order", base=base)[0]};'
            f'border:1px solid {pal.border};"></span>'
            for i in range(12)
        )
        key = (f'{swatches}<span style="color:{pal.muted}">study first &rarr; last '
               f'(1&ndash;{n_order})</span>')
    else:
        key = (f'<span style="color:{pal.muted}">each concept has its own stable '
               'colour (identity, not order)</span>')
    return (
        f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;'
        f'color:{pal.text};margin:6px 2px 0;display:flex;align-items:center;gap:8px;'
        f'flex-wrap:wrap">'
        f'<span style="color:{pal.muted}">Colour:</span>{key}'
        f'<span style="color:{pal.muted}">&middot; Badge = learner-order position &middot; '
        f'Showing {n_shown} of {n_total} concepts &middot; drag the frame\'s '
        f'bottom-right corner to resize</span></div>'
    )


def dag_html(graph: dict, base: str = None) -> str:
    """Render a course graph dict as self-contained interactive HTML.

    Expected payload shape (matching ``CourseGraphOut``):
        {course_id, nodes: [name...], edges: [{source, target, confidence}],
         node_count, edge_count, is_dag, topological_order}

    Layout: hierarchical top-down, prerequisites above dependents (mirrors the
    topological learner order). Node tooltip = learner-order position; edge
    tooltip = confidence + where the link came from (spoken transcript vs
    classifier) + the verbatim evidence sentence when one exists. Empty graphs
    return a short placeholder message instead of an empty canvas.

    This page is loaded in its own frame, so it cannot inherit the dashboard's
    CSS: its background, node fills, labels and edges are all written out from
    the theme tokens, or it would render as a white canvas in a dark app.
    """
    pal = theme.palette(base)
    nodes = graph.get("nodes") or []
    if not nodes:
        return (
            f'<body style="background:{pal.graph_bg};color:{pal.text};'
            'font-family:Segoe UI,Arial,sans-serif">'
            "<p>No graph yet &mdash; run &lsquo;Extract concepts + build graph&rsquo; "
            "from the Student dashboard, then reload this view.</p></body>"
        )

    # A5: pyvis is a heavy, lazy dependency — a missing/broken install must not
    # traceback the whole Faculty dashboard, just the interactive canvas.
    try:
        Network = _load_pyvis_network()
    except ImportError:
        return (
            f'<body style="background:{pal.graph_bg};color:{pal.text};'
            'font-family:Segoe UI,Arial,sans-serif">'
            "<p>The interactive DAG add-on (pyvis / vis-network) is not "
            "available on this install. Use the learner-order list below "
            "instead.</p></body>"
        )

    order = graph.get("topological_order") or list(nodes)
    n = max(len(order), 1)
    rank = {name: i for i, name in enumerate(order)}

    net = Network(
        height="720px",
        width="100%",
        directed=True,
        bgcolor=pal.graph_bg,
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
    "color": { "color": "%(graph_edge)s" }
  },
  "nodes": {
    "font": { "face": "Arial", "size": 13, "color": "%(text)s" },
    "borderWidth": 1,
    "shape": "dot"
  }
}
""" % {"graph_edge": pal.graph_edge, "text": pal.text}
    )
    for name in nodes:
        pos = rank.get(name, n - 1)
        frac = pos / max(n - 1, 1)
        # teal (early, should-learn-first) -> coral (late), the same ramp the
        # inline SVG uses, at this theme's node lightness
        fill, ink = node_colors(name, pos, n, mode="order", base=base)
        net.add_node(
            name,
            label=name,
            title="%s<br/>learner order #%d/%d" % (_html.escape(str(name)), pos + 1, n),
            color={"background": fill, "border": ink, "font": {"color": ink}},
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