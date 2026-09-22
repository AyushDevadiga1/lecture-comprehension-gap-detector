"""Course teardown — delete every DB row belonging to a course.

Media files on disk are the caller's job (routes own their file layout).
"""

from backend.models.db import (
    Clip,
    Concept,
    ConceptItem,
    GraphEdge,
    GraphNode,
    Lecture,
    LectureLink,
    Passage,
    QuizResponse,
    SessionLocal,
    TranscriptSegment,
)


def purge_course(course_id: str) -> int:
    """Delete every DB row belonging to a course and return lectures removed.

    Covers both lecture-scoped rows (segments, concepts, passages, links,
    clips) and the course-scoped tables that outlive lecture deletion
    (graph nodes/edges, quiz questions, quiz responses) — the exact gap that
    left stale smoke-test courses behind. Idempotent.
    """
    with SessionLocal() as db:
        lect_ids = [
            row[0]
            for row in db.query(Lecture.id).filter(Lecture.course_id == course_id).all()
        ]
        db.query(QuizResponse).filter(QuizResponse.course_id == course_id).delete(
            synchronize_session=False
        )
        db.query(ConceptItem).filter(ConceptItem.course_id == course_id).delete(
            synchronize_session=False
        )
        db.query(GraphEdge).filter(GraphEdge.course_id == course_id).delete(
            synchronize_session=False
        )
        db.query(GraphNode).filter(GraphNode.course_id == course_id).delete(
            synchronize_session=False
        )
        for lid in lect_ids:
            db.query(Clip).filter(Clip.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(LectureLink).filter(LectureLink.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(Passage).filter(Passage.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(Concept).filter(Concept.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(TranscriptSegment).filter(
                TranscriptSegment.lecture_id == lid
            ).delete(synchronize_session=False)
            db.query(Lecture).filter(Lecture.id == lid).delete(
                synchronize_session=False
            )
        db.commit()
        return len(lect_ids)