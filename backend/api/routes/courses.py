"""Course endpoints — per-course prerequisite graph build/fetch, the faculty
stats view (Stage 8), course listing and course cleanup. All paths live under
/courses."""

import os
import shutil
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import func

from backend.api import graphs, jobs
from backend.api.jobs.progress import get_lecture_progress
from backend.api.schemas import (
    CourseBuildOut,
    CourseDeleteOut,
    CourseGraphOut,
    CourseSummaryOut,
)
from backend.config import CLIPS_BASE_DIR
from backend.models.db import (
    Clip,
    Concept,
    ConceptItem,
    GraphEdge,
    GraphNode,
    Lecture,
    QuizResponse,
    SessionLocal,
)

router = APIRouter(prefix="/courses", tags=["courses"])

CLIPS_DIR = CLIPS_BASE_DIR


def _validate_course_id(course_id: str) -> str:
    """Reject course_id values that could produce SQL/path injection vectors.

    Allows alphanumeric characters, hyphens, and underscores only.
    Raises HTTP 422 for anything that doesn't match.
    """
    import re as _re
    if not _re.fullmatch(r"[\w\-]{1,128}", course_id):
        raise HTTPException(
            status_code=422, detail="course_id must be 1-128 alphanumeric/hyphen/underscore chars"
        )
    return course_id


@router.get("", response_model=List[CourseSummaryOut])
def list_courses() -> List[CourseSummaryOut]:
    """Teacher-dashboard course list (review_1 C2): one row per course with
    lecture/concept/graph counts so stale junk courses are obvious.

    M4 / P9: counts are aggregated in four grouped queries instead of the
    prior per-course N+1 loop (one COUNT per table per course was O(lectures)
    round-trips even for a single course).
    """
    with SessionLocal() as db:
        lectures = db.query(Lecture).order_by(Lecture.id).all()
        concept_counts = dict(
            db.query(Concept.course_id, func.count(Concept.id))
            .group_by(Concept.course_id)
            .all()
        )
        node_counts = dict(
            db.query(GraphNode.course_id, func.count(GraphNode.id))
            .group_by(GraphNode.course_id)
            .all()
        )
        edge_counts = dict(
            db.query(GraphEdge.course_id, func.count(GraphEdge.id))
            .group_by(GraphEdge.course_id)
            .all()
        )
    course_ids = sorted({lec.course_id for lec in lectures})
    summaries: List[CourseSummaryOut] = []
    for cid in course_ids:
        lecs = [lec for lec in lectures if lec.course_id == cid]
        node_count = node_counts.get(cid, 0)
        summaries.append(
            CourseSummaryOut(
                course_id=cid,
                total_lectures=len(lecs),
                ready_lectures=sum(1 for lec in lecs if lec.status == "ready"),
                total_concepts=concept_counts.get(cid, 0),
                node_count=node_count,
                edge_count=edge_counts.get(cid, 0),
                has_graph=node_count > 0,
            )
        )
    return summaries


@router.get("/{course_id}/snapshot")
def course_snapshot(course_id: str) -> dict:
    """Derived, live course readiness (plan/FRONTEND_ARCHITECTURE.md §13, B1).

    Cheap grouped counts + the lecture rows currently in flight
    (``uploaded``|``transcribing``) enriched with the live progress stage, so a
    5s frontend poll can show per-course state consistently across dashboards
    without a job registry. Never 404 — unknown courses return ``exists: false``.
    """
    course_id = _validate_course_id(course_id)
    with SessionLocal() as db:
        lectures = (
            db.query(Lecture)
            .filter(Lecture.course_id == course_id)
            .order_by(Lecture.id)
            .all()
        )
        concept_count = (
            db.query(func.count(Concept.id))
            .filter(Concept.course_id == course_id).scalar() or 0
        )
        clip_totals = dict(
            db.query(Clip.ok, func.count(Clip.id))
            .join(Lecture, Clip.lecture_id == Lecture.id)
            .filter(Lecture.course_id == course_id)
            .group_by(Clip.ok)
            .all()
        )
        question_count = (
            db.query(func.count(ConceptItem.id))
            .filter(ConceptItem.course_id == course_id).scalar() or 0
        )
        respondents = (
            db.query(func.count(func.distinct(QuizResponse.student_id)))
            .filter(QuizResponse.course_id == course_id).scalar() or 0
        )

    graph = graphs.course_graph(course_id) or {}
    node_count = graph.get("node_count", 0)
    edge_count = graph.get("edge_count", 0)

    statuses = {"total": len(lectures), "ready": 0, "uploaded": 0,
                "transcribing": 0, "error": 0}
    in_flight: List[dict] = []
    for lec in lectures:
        if lec.status in ("ready", "uploaded", "transcribing", "error"):
            statuses[lec.status] += 1
        if lec.status in ("uploaded", "transcribing"):
            prog = get_lecture_progress(lec.id)
            in_flight.append({
                "lecture_id": lec.id,
                "title": lec.title,
                "status": lec.status,
                "stage": (prog or {}).get("stage", lec.status),
                "progress_pct": (prog or {}).get("progress_pct", 0),
            })

    ok_clips = int(clip_totals.get(1, 0))
    return {
        "exists": bool(lectures) or concept_count > 0 or node_count > 0,
        "course_id": course_id,
        "lectures": statuses,
        "concepts": concept_count,
        "graph": {"has": node_count > 0, "nodes": node_count, "edges": edge_count},
        "clips": {"cut": ok_clips + int(clip_totals.get(0, 0)), "ok": ok_clips},
        "quiz": {"questions": question_count, "respondents": respondents},
        "in_flight": in_flight,
    }


@router.get("/{course_id}/graph", response_model=CourseGraphOut)
def get_course_graph(course_id: str) -> CourseGraphOut:
    """Fetch a course's persisted prerequisite graph and learner order.

    The read, cycle resolution, and M5 memoization live in the shared
    backend/api/graphs.py module (the quiz endpoints consume the same dict);
    this route only validates the id, turns "no rows" into a 404, and shapes
    the response.
    """
    course_id = _validate_course_id(course_id)
    data = graphs.course_graph(course_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No graph for this course")
    return CourseGraphOut(course_id=course_id, **data)


@router.post("/{course_id}/graph", response_model=CourseBuildOut, status_code=202)
def build_course_graph(
    course_id: str,
    background_tasks: BackgroundTasks,
    lecture_id: Optional[int] = None,
) -> CourseBuildOut:
    """Build (or rebuild) the prerequisite graph for a course in the background.

    Collects the course's extracted concepts, scores candidate pairs with the
    LectureBank-trained classifier (Stage 3), and persists the deduplicated
    nodes + acyclic edges (Stage 4). Rows are replaced per course on re-run,
    so the Stage 7 refinement loop can update the graph safely.

    ``lecture_id`` optionally links the rebuild's progress updates to one
    lecture (the UI's selected one) so the Streamlit progress monitor has a
    row to watch and a `ready` terminal state.
    """
    course_id = _validate_course_id(course_id)
    background_tasks.add_task(
        jobs.build_course_graph_worker, course_id.strip(), lecture_id
    )
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
    course_id = _validate_course_id(course_id)
    with SessionLocal() as db:
        # M5: aggregate the heatmap in SQL instead of hydrating every
        # QuizResponse row into Python (previously all course responses were
        # loaded, then tallied per concept).
        per_concept = {}
        for concept, attempts, correct_sum in (
            db.query(QuizResponse.concept,
                     func.count(QuizResponse.id),
                     func.sum(QuizResponse.correct))
            .filter(QuizResponse.course_id == course_id)
            .group_by(QuizResponse.concept)
            .all()
        ):
            correct = correct_sum or 0
            per_concept[concept] = [attempts - correct, attempts]

        concepts = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.start_s)
            .all()
        )

    # order taught = earliest mention (start_s) of each concept in lectures
    taught_order = []
    seen = set()
    for c in concepts:
        if c.name not in seen:
            seen.add(c.name)
            taught_order.append(c.name)

    data = graphs.course_graph(course_id)
    learned_order = data["topological_order"] if data else taught_order

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
    responses via jobs.purge_course) plus raw media and cut clips on disk."""
    course_id = _validate_course_id(course_id.strip())

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

    n_removed = jobs.purge_course(course_id)

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