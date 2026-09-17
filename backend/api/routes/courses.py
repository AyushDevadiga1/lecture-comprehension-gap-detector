"""Course endpoints — per-course prerequisite graph build/fetch, the faculty
stats view (Stage 8), course listing and course cleanup. All paths live under
/courses."""

import os
import shutil
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException

from backend.api import workers
from backend.api.schemas import (
    CourseBuildOut,
    CourseDeleteOut,
    CourseGraphOut,
    CourseSummaryOut,
)
from backend.models.db import (
    Concept,
    GraphEdge,
    GraphNode,
    Lecture,
    QuizResponse,
    SessionLocal,
)
from backend.pipeline.build_graph import ConceptGraph

router = APIRouter(prefix="/courses", tags=["courses"])

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIPS_DIR = REPO_ROOT / "data" / "processed" / "clips"


@router.get("", response_model=List[CourseSummaryOut])
def list_courses() -> List[CourseSummaryOut]:
    """Teacher-dashboard course list (review_1 C2): one row per course with
    lecture/concept/graph counts so stale junk courses are obvious."""
    with SessionLocal() as db:
        lectures = db.query(Lecture).order_by(Lecture.id).all()
    course_ids = sorted({lec.course_id for lec in lectures})
    summaries: List[CourseSummaryOut] = []
    with SessionLocal() as db:
        for cid in course_ids:
            lecs = [lec for lec in lectures if lec.course_id == cid]
            summaries.append(
                CourseSummaryOut(
                    course_id=cid,
                    total_lectures=len(lecs),
                    ready_lectures=sum(1 for lec in lecs if lec.status == "ready"),
                    total_concepts=(
                        db.query(Concept).filter(Concept.course_id == cid).count()
                    ),
                    node_count=(
                        db.query(GraphNode).filter(GraphNode.course_id == cid).count()
                    ),
                    edge_count=(
                        db.query(GraphEdge).filter(GraphEdge.course_id == cid).count()
                    ),
                    has_graph=(
                        db.query(GraphNode).filter(GraphNode.course_id == cid).count()
                        > 0
                    ),
                )
            )
    return summaries


@router.get("/{course_id}/graph", response_model=CourseGraphOut)
def get_course_graph(course_id: str) -> CourseGraphOut:
    """Fetch a course's persisted prerequisite graph and learner order.

    The stored edges/nodes are already acyclic (cycles were broken at build
    time by dropping lowest-confidence edges), so this recomputes the
    topological order from the persisted rows.
    """
    with SessionLocal() as db:
        node_rows = (
            db.query(GraphNode)
            .filter(GraphNode.course_id == course_id)
            .order_by(GraphNode.id)
            .all()
        )
        if not node_rows:
            raise HTTPException(status_code=404, detail="No graph for this course")
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
    return CourseGraphOut(course_id=course_id, **result)


def _course_graph_dict(course_id: str) -> dict:
    """Course graph as plain dict {edges, topological_order} for pipeline helpers."""
    out = get_course_graph(course_id)
    return {
        "edges": [{"source": e.source, "target": e.target,
                   "confidence": e.confidence,
                   "source_method": e.source_method,
                   "evidence": e.evidence} for e in out.edges],
        "topological_order": out.topological_order,
    }


@router.post("/{course_id}/graph", response_model=CourseBuildOut, status_code=202)
def build_course_graph(
    course_id: str, background_tasks: BackgroundTasks
) -> CourseBuildOut:
    """Build (or rebuild) the prerequisite graph for a course in the background.

    Collects the course's extracted concepts, scores candidate pairs with the
    LectureBank-trained classifier (Stage 3), and persists the deduplicated
    nodes + acyclic edges (Stage 4). Rows are replaced per course on re-run,
    so the Stage 7 refinement loop can update the graph safely.
    """
    background_tasks.add_task(workers._build_course_graph_worker, course_id.strip())
    return CourseBuildOut(status="queued", course_id=course_id.strip())


@router.get("/{course_id}/stats")
def course_stats(course_id: str) -> dict:
    """Stage 8 — confusion heatmap + taught-vs-learned divergence.

    Heatmap: per concept, wrong-answer rate (0..1) across students (optionally
    bucketed by attempt — a single first-attempt number here, extendable).
    Divergence: index of each concept in the ORDER TAUGHT (lecture sequence,
    i.e. earliest concept timestamp) vs. the order the learned graph says it
    should be LEARNED (topological). Concepts with a big gap are the
    divergence view.
    """
    with SessionLocal() as db:
        rows = (
            db.query(QuizResponse)
            .filter(QuizResponse.course_id == course_id)
            .all()
        )
        concepts = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.start_s)
            .all()
        )

    per_concept: dict = {}
    for r in rows:
        per_concept.setdefault(r.concept, [0, 0])
        per_concept[r.concept][1] += 1
        if not r.correct:
            per_concept[r.concept][0] += 1

    # order taught = earliest mention (start_s) of each concept in lectures
    taught_order = []
    seen = set()
    for c in concepts:
        if c.name not in seen:
            seen.add(c.name)
            taught_order.append(c.name)

    try:
        learned_order = get_course_graph(course_id).topological_order
    except HTTPException:
        learned_order = taught_order

    heatmap = [
        {"concept": name, "wrong": wrong, "attempts": total,
         "rate": (wrong / total) if total else 0.0}
        for name, (wrong, total) in per_concept.items()
    ]
    heatmap.sort(key=lambda x: -x["rate"])

    divergence = []
    for name in set(taught_order) | set(learned_order):
        ti = taught_order.index(name) if name in taught_order else None
        li = learned_order.index(name) if name in learned_order else None
        if ti is not None and li is not None:
            divergence.append(
                {"concept": name, "taught_idx": ti, "learned_idx": li,
                 "gap": li - ti}
            )
    divergence.sort(key=lambda x: -abs(x["gap"]))

    return {
        "course_id": course_id,
        "heatmap": heatmap,
        "divergence": divergence,
        "taught_order": taught_order,
        "learned_order": learned_order,
    }


@router.delete("/{course_id}", response_model=CourseDeleteOut)
def delete_course(course_id: str) -> CourseDeleteOut:
    """Nuke a course: every DB row (lectures + course-scoped graph/questions/
    responses via workers.purge_course) plus raw media and cut clips on disk."""
    course_id = course_id.strip()

    with SessionLocal() as db:
        lecs = (
            db.query(Lecture).filter(Lecture.course_id == course_id).all()
        )
        has_leftovers = (
            db.query(Concept).filter(Concept.course_id == course_id).first()
            or db.query(GraphNode).filter(GraphNode.course_id == course_id).first()
        )

    if not lecs and not has_leftovers:
        raise HTTPException(
            status_code=404, detail=f"Course '{course_id}' not found"
        )

    n_removed = workers.purge_course(course_id)

    for lec in lecs:
        if lec.source_path:
            try:
                os.remove(lec.source_path)
            except OSError:
                pass
        shutil.rmtree(CLIPS_DIR / str(lec.id), ignore_errors=True)

    return CourseDeleteOut(
        deleted=True,
        course_id=course_id,
        lectures_removed=n_removed,
        message=f"Course '{course_id}' deleted ({n_removed} lectures, media + clips removed)",
    )