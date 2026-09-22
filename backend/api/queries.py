"""Cross-endpoint read helpers shared by the route layer.

Pure DB reads / pure presentation — no HTTP, no job orchestration. Lives
outside the jobs package because routes need these synchronously, not as
background work.
"""

from backend.api.schemas import QuizQuestionOut
from backend.models.db import Clip, Lecture, SessionLocal, TranscriptSegment


def lecture_segments(db, course_id: str) -> list:
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


def question_out(item) -> QuizQuestionOut:
    """Present a stored question with its options in shuffled order."""
    import random

    options = [item.answer] if item.answer else []
    options += [
        d
        for d in (item.distractor_a, item.distractor_b, item.distractor_c)
        if d and d != item.answer
    ]
    rnd = random.SystemRandom()
    rnd.shuffle(options)
    return QuizQuestionOut(
        id=item.id,
        concept=item.concept,
        question=item.question,
        options=options,
    )


def clips_by_concept(course_id: str) -> dict:
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