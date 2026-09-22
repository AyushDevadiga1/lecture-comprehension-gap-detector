"""Stage 4 job — regenerate a course's prerequisite graph from its concepts."""

from backend.api.jobs.common import client_error_message, get_shared_classifier
from backend.api.jobs.progress import _finish, update_lecture_progress
from backend.config import llm_reasoning_enabled
from backend.models.db import Concept, GraphEdge, GraphNode, Lecture, LectureLink, SessionLocal
from backend.pipeline.build_graph import ConceptGraph


def build_course_graph_worker(course_id: str, lecture_id: int = None) -> None:
    """Background worker: dedup concept names, score edges, persist per-course.

    No-op when the course has no concept rows yet — the concept-extraction
    worker rebuilds the graph itself once its new concepts are persisted, so a
    caller that fires this before extraction finishes still ends up correct.

    ``lecture_id`` (optional, forwarded from POST /courses/{id}/graph) ties the
    rebuild's progress updates to one lecture so the Streamlit monitor sees the
    job move and settle on a `ready` status instead of polling an untouched
    lecture row forever.
    """
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 55,
            "Loading shared concept encoder...", status="building_graph",
        )
    try:
        rebuild_course_graph(course_id.strip(), lecture_id=lecture_id)
    except Exception as exc:  # noqa: BLE001
        if lecture_id is not None:
            err_msg = client_error_message(exc, "Course-graph rebuild")
            update_lecture_progress(
                lecture_id, "error", 0, err_msg, status="error",
            )
            with SessionLocal() as db:
                lecture = db.get(Lecture, lecture_id)
                if lecture is not None:
                    lecture.status = "error"
                    lecture.error = err_msg
                    db.commit()
            _finish(lecture_id)
        return
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "ready", 100, "Course graph rebuilt.", status="building_graph",
        )
        _finish(lecture_id)


def rebuild_course_graph(course_id: str, lecture_id: int = None) -> None:
    """Regenerate a course's prerequisite graph from its current concept rows.

    Transcript-first (plan/LECTURE_STRUCTURE.md §4): lecture_links persisted by
    the extraction pass become edges at confidence 0.9 with their verbatim
    evidence (`source_method="transcript"`); the LectureBank classifier then
    fills ONLY pairs the transcript never grounded (`source_method="classifier"`),
    which is where cross-lecture relations and silent jumps live. Cycle
    resolution is unchanged — it drops the lowest-confidence edge on a cycle, so
    transcript edges (0.9) dominate by design.
    Shared by POST /courses/{id}/graph and the concept-extraction worker so
    the graph always reflects the latest extracted concept set regardless of
    call order (the UI fires both requests back-to-back; without this chaining
    the graph request can query an empty Concept table and silently exit).
    Idempotent — existing rows are replaced per course on re-run.

    ``lecture_id`` ties progress updates to the lecture that triggered the
    rebuild (extraction worker passes its own id so the progress bar moves).
    """
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 60, "Loading shared concept encoder...",
            status="building_graph",
        )

    with SessionLocal() as db:
        rows = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.id)
            .all()
        )
        if not rows:
            if lecture_id is not None:
                _finish(lecture_id)
            return
        concepts = [
            {"name": c.name, "start_s": c.start_s, "end_s": c.end_s} for c in rows
        ]
        lect_ids = [
            row[0]
            for row in db.query(Lecture.id).filter(Lecture.course_id == course_id).all()
        ]
        link_rows = []
        if lect_ids:
            link_rows = (
                db.query(LectureLink)
                .filter(LectureLink.lecture_id.in_(lect_ids))
                .all()
            )
        # one edge per (source, target), keeping the first verbatim evidence
        pair_by: dict = {}
        for r in link_rows:
            key = (r.source_name, r.target_name)
            if key not in pair_by:
                pair_by[key] = r.evidence or None
        link_pairs = [(a, b, ev) for (a, b), ev in pair_by.items()]

    names = sorted({c["name"] for c in concepts})

    # Load/keep the shared embedding model + fitted head (H4): one
    # MiniLM instance serves concept dedup, the candidate pre-filter, and the
    # classifier fit/predict across every rebuild for the process lifetime.
    from backend.pipeline.classify_prerequisites import classify_course_pairs

    clf = get_shared_classifier()
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 75, f"Deduplicating {len(names)} concepts...",
            status="building_graph",
        )
    graph = ConceptGraph(encoder_fn=clf._get_encoder)
    graph.add_concepts(names)
    g = graph.to_networkx()
    edge_meta: dict = {}
    # Only the concepts extracted (and dedup-canonicalised) above are valid
    # nodes. A spoken link whose endpoints were never extracted (LLM
    # hallucination, name variant, cross-lecture reference) is dropped here —
    # letting add_edge auto-create it (build_graph.add_edge) would plant a
    # GraphNode with no Concept row in topo order and remediation.
    known_nodes = set(graph.nodes())
    for a, b, ev in link_pairs:
        a_res, b_res = graph._resolve(a), graph._resolve(b)
        if a_res not in known_nodes or b_res not in known_nodes:
            continue
        edge_meta[(a_res, b_res)] = ("transcript", ev)
        graph.add_edge(a, b, 0.9)
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 85, "Scoring candidate prerequisite pairs...",
            status="building_graph",
        )
    try:
        confirmed = classify_course_pairs(concepts, encoder=clf._encoder)
    except ValueError:
        confirmed = []  # LectureBank absent on this deployment -> nodes-only

    use_llm_reasoning = llm_reasoning_enabled()
    from backend.pipeline.classify_prerequisites import llm_reasoning_check

    for e in confirmed:
        a_res, b_res = graph._resolve(e["a"]), graph._resolve(e["b"])
        if g.has_edge(a_res, b_res):
            continue  # already grounded by the transcript — keep the spoken edge
        method, reason = "classifier", None
        add_conf = e["confidence"]
        if use_llm_reasoning:
            try:
                # M1: the LLM second opinion modulates the edge's confidence
                # (adjusted_confidence) — it never hard-vetoes an edge, because
                # a fallible, prompt-injectable verdict deleting a learned
                # prerequisite silently would corrupt the DAG.
                chk = llm_reasoning_check(e["a"], e["b"], prediction=1, confidence=e["confidence"])
                add_conf = chk.get("adjusted_confidence", add_conf)
                reason = chk.get("reason")
                method = "classifier+llm"
            except Exception:
                pass
        graph.add_edge(e["a"], e["b"], add_conf)
        edge_meta[(a_res, b_res)] = (method, reason)
    graph.resolve_cycles()

    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 92, "Persisting graph rows...",
            status="building_graph",
        )
    with SessionLocal() as db:
        db.query(GraphNode).filter(GraphNode.course_id == course_id).delete()
        db.query(GraphEdge).filter(GraphEdge.course_id == course_id).delete()
        for name in graph.nodes():
            db.add(GraphNode(course_id=course_id, name=name))
        for e in graph.edges():
            method, evidence = edge_meta.get(
                (e["source"], e["target"]), ("classifier", None)
            )
            db.add(
                GraphEdge(
                    course_id=course_id,
                    source=e["source"],
                    target=e["target"],
                    confidence=e["confidence"],
                    source_method=method,
                    evidence=evidence,
                )
            )
        db.commit()
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 98, f"{len(graph.nodes())} nodes, "
            f"{len(graph.edges())} edges persisted.",
            status="building_graph",
        )