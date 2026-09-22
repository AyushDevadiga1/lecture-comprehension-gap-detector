"""Course-graph reads — the one deep interface graph consumers share.

Both the /courses graph route and the quiz/remediation endpoints need the same
thing: a course's persisted prerequisite graph as a plain dict, with cycles
resolved and edge provenance re-attached. Hosting that here (instead of a route
module importing another route module) keeps the read in one place and gives
every consumer the same input shape.

The M5 memo lives here too — it is a property of *reading* the graph, not of
the /courses router: keyed by (sessionmaker, course_id) and validated against a
cheap row signature, so any direct row write (a rebuild, a purge) self-heals
the entry on the next poll.
"""

import threading

from sqlalchemy import func

from backend.models.db import GraphEdge, GraphNode, SessionLocal
from backend.pipeline.build_graph import ConceptGraph

_GRAPH_CACHE: dict = {}
_GRAPH_LOCK = threading.Lock()
_GRAPH_CACHE_MAX = 128  # prevent unbounded memory growth


def graph_signature(db, course_id: str) -> tuple:
    """Cheap fingerprint of a course's persisted graph rows (counts + max id).
    Any rebuild/delete changes at least one field, forcing a cache rebuild."""
    node_count = (
        db.query(func.count(GraphNode.id))
        .filter(GraphNode.course_id == course_id)
        .scalar()
    )
    edge_count = (
        db.query(func.count(GraphEdge.id))
        .filter(GraphEdge.course_id == course_id)
        .scalar()
    )
    max_node = (
        db.query(func.max(GraphNode.id))
        .filter(GraphNode.course_id == course_id)
        .scalar()
    )
    max_edge = (
        db.query(func.max(GraphEdge.id))
        .filter(GraphEdge.course_id == course_id)
        .scalar()
    )
    return (node_count or 0, edge_count or 0, max_node or 0, max_edge or 0)


def course_graph(course_id: str):
    """A course's prerequisite graph as a plain dict — or None when absent.

    The stored edges/nodes are already acyclic (cycles were broken at build
    time by dropping lowest-confidence edges), so the topological order is
    recomputed from the persisted rows. Edges carry their provenance
    (`source_method`/`evidence`) so consumers can explain why an edge exists.
    Returns None when the course has no graph rows yet (no HTTPException — that
    is the caller's decision to make up).
    """
    with SessionLocal() as db:
        signature = graph_signature(db, course_id)
        key = (SessionLocal, course_id)
        with _GRAPH_LOCK:
            cached = _GRAPH_CACHE.get(key)
            if cached is not None and cached[0] == signature:
                return cached[1]

        node_rows = (
            db.query(GraphNode)
            .filter(GraphNode.course_id == course_id)
            .order_by(GraphNode.id)
            .all()
        )
        if not node_rows:
            return None
        edge_rows = db.query(GraphEdge).filter(GraphEdge.course_id == course_id).all()

    graph = ConceptGraph()
    graph.add_concepts_verbatim([n.name for n in node_rows])  # stored names are canonical
    for e in edge_rows:
        graph.add_edge(e.source, e.target, e.confidence)
    graph.resolve_cycles()
    result = graph.to_dict()
    # re-attach the persisted provenance the graph object itself doesn't carry
    # (transcript|classifier source + verbatim evidence) so the DAG view can
    # render WHY an edge exists (Stage 8).
    edge_info = {
        (e.source, e.target): (e.source_method or "classifier", e.evidence or None)
        for e in edge_rows
    }
    for ed in result["edges"]:
        ed["source_method"], ed["evidence"] = edge_info.get(
            (ed["source"], ed["target"]), ("classifier", None)
        )
    with _GRAPH_LOCK:
        # Evict oldest entries when cache is full
        if len(_GRAPH_CACHE) >= _GRAPH_CACHE_MAX:
            _GRAPH_CACHE.pop(next(iter(_GRAPH_CACHE)), None)
        _GRAPH_CACHE[key] = (signature, result)
    return result