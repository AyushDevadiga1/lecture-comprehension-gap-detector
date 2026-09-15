"""Background workers + shared DB/pipeline helpers — moved out of routes.py.

Holds every long-running job the endpoints schedule (transcription, concept
extraction, clip cutting, course-graph rebuild) plus the cross-endpoint query
helpers. Endpoints stay thin: they validate input, schedule a worker, and read
back rows. Purely server-side — no HTTP logic lives here beyond what the route
layer calls.
"""

from datetime import datetime
from pathlib import Path
from typing import List

from backend.models.db import (
    Clip,
    Concept,
    GraphEdge,
    GraphNode,
    Lecture,
    SessionLocal,
    TranscriptSegment,
)
from backend.pipeline.build_graph import ConceptGraph
from backend.pipeline.extract_concepts import extract_spoken_concepts
from backend.pipeline.refine_timeline import refine_concept_times
from backend.pipeline.segment_clips import cut_concept_clips
from backend.pipeline.transcribe import transcribe
from backend.api.schemas import QuizQuestionOut

REPO_ROOT = Path(__file__).resolve().parents[2]


def _process_lecture(lecture_id: int) -> None:
    """Background worker: transcribe one lecture and persist its segments."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            return
        lecture.status = "transcribing"
        db.commit()
        source_path = lecture.source_path

    try:
        segments = transcribe(source_path)
    except Exception as exc:  # noqa: BLE001 — surface any failure on the lecture row
        with SessionLocal() as db:
            lecture = db.get(Lecture, lecture_id)
            if lecture is not None:
                lecture.status = "error"
                lecture.error = f"{type(exc).__name__}: {exc}"[:2000]
                db.commit()
        return

    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            return
        lecture.segments.clear()
        for i, seg in enumerate(segments):
            db.add(
                TranscriptSegment(
                    lecture_id=lecture_id,
                    idx=i,
                    start_s=seg["start"],
                    end_s=seg["end"],
                    text=seg["text"],
                )
            )
        lecture.status = "ready"
        lecture.processed_at = datetime.now().astimezone()
        db.commit()


def _extract_concepts_worker(lecture_id: int) -> None:
    """Background worker: run spoken concept extraction and persist rows."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            return
        docs = [
            {"start_s": s.start_s, "end_s": s.end_s, "text": s.text}
            for s in lecture.segments
        ]
        course_id = lecture.course_id

    try:
        concepts = extract_spoken_concepts(docs)
        # Stage 2b: the extractor stamps each concept with its whole chunk's
        # span (often minutes). Pin it down to where the concept is actually
        # taught so Stage 5 clips stay watchable and the coverage band is honest.
        concepts = refine_concept_times(concepts, docs)
    except Exception as exc:  # noqa: BLE001 — any failure is fine to surface
        with SessionLocal() as db:
            lecture = db.get(Lecture, lecture_id)
            if lecture is not None:
                lecture.error = f"{type(exc).__name__}: {exc}"[:2000]
                db.commit()
        return

    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            return
        lecture.error = None  # a success supersedes any earlier failed run
        db.query(Concept).filter(Concept.lecture_id == lecture_id).delete()
        for c in concepts:
            db.add(
                Concept(
                    course_id=course_id,
                    lecture_id=lecture_id,
                    name=c["name"],
                    source=c["source"],
                    implicit=int(c["implicit"]),
                    start_s=c.get("start_s"),
                    end_s=c.get("end_s"),
                )
            )
        db.commit()

    # Stage 3/4 chained server-side: rebuilding the course graph here — after
    # the fresh concepts are persisted — closes the UI race where a parallel
    # POST /courses/{id}/graph queries an empty Concept table and silently
    # exits. Idempotent, so an explicit graph build is harmless either way.
    _rebuild_course_graph(course_id)


def _cut_clips_worker(lecture_id: int) -> None:
    """Background worker: cut one clip per concept and persist the rows."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            return
        media_path = lecture.source_path
        concepts = [
            {
                "name": c.name,
                "start_s": c.start_s,
                "end_s": c.end_s,
                "concept_id": c.id,
            }
            for c in lecture.concepts
        ]

    out_dir = REPO_ROOT / "data" / "processed" / "clips" / str(lecture_id)
    results = cut_concept_clips(str(media_path) if media_path else "", concepts, out_dir)

    with SessionLocal() as db:
        db.query(Clip).filter(Clip.lecture_id == lecture_id).delete()
        for concept, res in zip(concepts, results):
            db.add(
                Clip(
                    lecture_id=lecture_id,
                    concept_id=concept["concept_id"],
                    concept_name=concept["name"],
                    start_s=concept["start_s"] or 0.0,
                    end_s=concept["end_s"] or 0.0,
                    path=res["path"] if res["path"] else "",
                    ok=int(bool(res["ok"])),
                    error=res.get("error"),
                )
            )
        db.commit()


def _build_course_graph_worker(course_id: str) -> None:
    """Background worker: dedup concept names, score edges, persist per-course.

    No-op when the course has no concept rows yet — the concept-extraction
    worker rebuilds the graph itself once its new concepts are persisted, so a
    caller that fires this before extraction finishes still ends up correct.
    """
    _rebuild_course_graph(course_id.strip())


def _rebuild_course_graph(course_id: str) -> None:
    """Regenerate a course's prerequisite graph from its current concept rows.

    Shared by POST /courses/{id}/graph and the concept-extraction worker so
    the graph always reflects the latest extracted concept set regardless of
    call order (the UI fires both requests back-to-back; without this chaining
    the graph request can query an empty Concept table and silently exit).
    Idempotent — existing rows are replaced per course on re-run.
    """
    from backend.pipeline import classify_prerequisites

    with SessionLocal() as db:
        rows = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.id)
            .all()
        )
        if not rows:
            return
        concepts = [
            {"name": c.name, "start_s": c.start_s, "end_s": c.end_s} for c in rows
        ]
    names = sorted({c["name"] for c in concepts})

    graph = ConceptGraph()
    graph.add_concepts(names)
    try:
        confirmed = classify_prerequisites.classify_course_pairs(concepts)
    except ValueError:
        confirmed = []  # LectureBank absent on this deployment -> nodes-only
    for e in confirmed:
        graph.add_edge(e["a"], e["b"], e["confidence"])
    graph.resolve_cycles()

    with SessionLocal() as db:
        db.query(GraphNode).filter(GraphNode.course_id == course_id).delete()
        db.query(GraphEdge).filter(GraphEdge.course_id == course_id).delete()
        for name in graph.nodes():
            db.add(GraphNode(course_id=course_id, name=name))
        for e in graph.edges():
            db.add(
                GraphEdge(
                    course_id=course_id,
                    source=e["source"],
                    target=e["target"],
                    confidence=e["confidence"],
                )
            )
        db.commit()


def _lecture_segments(db, course_id: str) -> List[TranscriptSegment]:
    """All transcript segments of a course's lectures, time-ordered."""
    lect_ids = [
        row[0]
        for row in db.query(Lecture.id).filter(Lecture.course_id == course_id).all()
    ]
    if not lect_ids:
        return []
    return (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.lecture_id.in_(lect_ids))
        .order_by(TranscriptSegment.start_s)
        .all()
    )


def _in_range(
    segments: List[TranscriptSegment],
    concept: Concept,
    margin_s: float = 0.5,
) -> List[TranscriptSegment]:
    """Segments that fall inside a concept's spoken window (+ margin)."""
    if concept.start_s is None:
        return segments
    return [
        s
        for s in segments
        if s.start_s >= concept.start_s - margin_s
        and s.end_s <= concept.end_s + margin_s
    ]


def _question_out(item) -> QuizQuestionOut:
    """Present a stored question with its options in shuffled order."""
    import random

    options = [item.answer] if item.answer else []
    options += [
        d
        for d in (item.distractor_a, item.distractor_b, item.distractor_c)
        if d and d != item.answer
    ]
    rnd = random.Random(f"{item.id}:{item.concept}")
    rnd.shuffle(options)
    return QuizQuestionOut(
        id=item.id,
        concept=item.concept,
        question=item.question,
        options=options,
        distractor_a=item.distractor_a,
        distractor_b=item.distractor_b,
        distractor_c=item.distractor_c,
    )


def _clips_by_concept(course_id: str) -> dict:
    """Concept name -> first ok clip path, for a course (via its lectures)."""
    with SessionLocal() as db:
        rows = (
            db.query(Clip).join(Lecture, Clip.lecture_id == Lecture.id)
            .filter(Lecture.course_id == course_id, Clip.ok == 1)
            .all()
        )
    out: dict = {}
    for clip in rows:
        out.setdefault(clip.concept_name, clip.path)
    return out