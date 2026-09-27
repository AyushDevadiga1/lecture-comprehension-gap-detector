"""Graph panel — the course prerequisite DAG for both dashboards.

The drawing is dependency-free inline SVG (see :mod:`frontend.render`) wrapped
in a scroll box, with the learner order shown both as a badge on every node and
as a contained, scrollable study sequence.
"""

import streamlit as st

from frontend import client, layout, state
from frontend.render import dag_svg, graph_importance

# A graph at or under this size is legible in full, so no filter is applied by
# default. Above it, the significance ranking kicks in.
READABLE_ALL = 60
DEFAULT_LIMIT = 40


def _controls(graph, key_prefix):
    """Zoom / edge-type / node-count controls, shared by both dashboards."""
    nodes = graph.get("nodes") or []
    methods_present = sorted({
        str(e.get("source_method", "classifier"))
        for e in (graph.get("edges") or [])
    }) or ["classifier"]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        zoom = st.slider("Zoom", 0.5, 2.0, 1.0, 0.1, key=f"{key_prefix}_zoom",
                         help="Scales the drawing. Scroll inside the box to pan, "
                              "or drag its bottom-right corner to resize it.")
    with c2:
        color_by = st.selectbox(
            "Colour by", ["order", "identity"], key=f"{key_prefix}_color",
            format_func=lambda v: ("Learner order (first → last)" if v == "order"
                                   else "Concept identity"),
            help="Learner order makes 'what do I study first' visible at a "
                 "glance. Identity gives every concept its own stable colour.")
    with c3:
        methods = st.multiselect(
            "Edge types", options=methods_present, default=methods_present,
            key=f"{key_prefix}_methods",
            help="Spoken-transcript links are the ones the professor stated out "
                 "loud; classifier links are inferred.")
    with c4:
        st.metric("Links drawn", _count_drawn(graph, methods, nodes))

    default_limit = len(nodes) if len(nodes) <= READABLE_ALL else DEFAULT_LIMIT
    limit = st.slider("Concepts shown", 5, max(len(nodes), 5), default_limit, 5,
                      key=f"{key_prefix}_limit",
                      help="Lower shows only the most significant concepts "
                           "(well-connected, specific names). Keyword fragments "
                           "like HAVING/update rank lowest.")
    return zoom, (methods or None), limit, color_by


def _count_drawn(graph, methods, nodes):
    kept, _ = graph_importance(graph, limit=len(nodes) or 1)
    wanted = {str(m) for m in (methods or ["classifier"])}
    return f"{sum(1 for e in (graph.get('edges') or []) if e.get('source') in kept and e.get('target') in kept and str(e.get('source_method', 'classifier')) in wanted)} / {len(graph.get('edges') or [])}"


def _study_sequence(graph, key_prefix):
    order = graph.get("topological_order") or []
    if not order:
        return
    st.markdown("**Learner order** — the sequence to study in")
    st.markdown(
        layout.definition_list([(i, n) for i, n in enumerate(order, 1)],
                               max_height=320),
        unsafe_allow_html=True,
    )


def render_course_graph(nav_course, key_prefix="sg"):
    """The course prerequisite DAG, with the payload kept in session state."""
    st.subheader("Course concept graph")
    if st.button("Load / refresh graph", key=f"{key_prefix}_load"):
        graph = client.course_graph(nav_course)
        if graph is not None:
            state.set("graph", data=graph, course=nav_course)
        else:
            err = client.take_last_error()
            st.error((err or {}).get("detail")
                     or "Graph load failed — no graph for this course yet "
                        "(extract concepts first), or the backend is down.")

    graph = state.get("graph", "data")
    if not graph or state.get("graph", "course") != nav_course:
        st.caption("Not loaded yet — press 'Load / refresh graph'. If the course "
                   "has no graph at all, run 'Extract concepts + build graph' on a "
                   "ready lecture first.")
        return
    nodes = graph.get("nodes") or []
    if not nodes:
        st.info("This course has no graph yet. Use 'Extract concepts + build graph' "
                "on a ready lecture, or 'Rebuild graph only'.")
        return

    zoom, methods, limit, color_by = _controls(graph, key_prefix)
    shown, dropped = graph_importance(graph, limit=limit)
    st.write(f"**{graph.get('node_count', len(nodes))} concepts in total · "
             f"{len(shown)} shown · "
             f"{'acyclic' if graph.get('is_dag') else 'contains cycles'}**")
    if dropped:
        st.caption(f"{len(dropped)} lower-significance concept(s) hidden to keep "
                   f"this readable. Raise the slider to include them.")
    st.caption("Prerequisites sit above what they unlock. Scroll inside the box to "
               "pan, drag its corner to resize, and hover an edge to see where the "
               "link came from and its evidence.")
    st.markdown(dag_svg(graph, max_nodes=limit, zoom=zoom, methods=methods,
                        color_by=color_by),
                unsafe_allow_html=True)
    _study_sequence(graph, key_prefix)


def render_faculty_dag(nav_course):
    """Faculty view of the same graph, with its own control state."""
    st.subheader("Concept prerequisite DAG")
    st.caption("Prerequisites sit above what they unlock. Scroll inside the box to "
               "pan, hover a node for its rank in the learner sequence, hover an "
               "edge for its confidence + whether the professor said it (spoken "
               "transcript) or the classifier inferred it + the evidence.")
    if st.button("Render DAG"):
        graph = client.course_graph(nav_course)
        if graph is not None:
            state.set("faculty", graph=graph, graph_course=nav_course)
        else:
            err = client.take_last_error()
            st.error((err or {}).get("detail")
                     or "Graph load failed — is the backend up?")

    graph = state.get("faculty", "graph")
    if not (graph and state.get("faculty", "graph_course") == nav_course):
        return
    nodes = graph.get("nodes") or []
    if not nodes:
        st.info("No nodes yet — run 'Extract concepts + build graph' from the "
                "Student dashboard.")
        return

    zoom, methods, limit, color_by = _controls(graph, "faculty")
    shown, dropped = graph_importance(graph, limit=limit)
    st.write(f"**{graph.get('node_count', len(nodes))} concepts · "
             f"{len(shown)} shown · "
             f"{'acyclic (DAG)' if graph.get('is_dag') else 'has cycles'}**")
    st.markdown(dag_svg(graph, max_nodes=limit, zoom=zoom, methods=methods,
                        color_by=color_by),
                unsafe_allow_html=True)
    _study_sequence(graph, "faculty")
