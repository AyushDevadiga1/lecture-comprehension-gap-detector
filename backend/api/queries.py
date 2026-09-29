"""Cross-endpoint read helpers shared by the route layer.

Pure DB reads / pure presentation — no HTTP, no job orchestration. Lives
outside the jobs package because routes need these synchronously, not as
background work.
"""

from pathlib import Path

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


def clip_media_url(clip_path, lecture_id):
    """The canonical playback URL for a stored clip path.

    One place, so no client has to reconstruct it. ``GET
    /media/clips/{lecture_id}/{filename}`` is the only thing that actually serves
    these bytes (``routes/media.py``), and it is Range-capable, so a URL is the
    only correct thing to hand a browser.

    Mirrors the ``_compute_url`` validator on ``ClipOut``; the two are asserted to
    agree by ``tests/test_contract.py``.
    """
    if not clip_path or not lecture_id:
        return None
    return f"/media/clips/{lecture_id}/{Path(clip_path).name}"


def clips_by_concept(course_id: str) -> dict:
    """Concept name -> first ok clip **URL** for a course (via its lectures).

    Contract v2: this used to return ``Clip.path``, a server filesystem path,
    which is why the React app carried a path-to-URL mapper and the Streamlit
    client still carries ``media_url``. A filesystem path in a payload is a
    contract-test failure (``plan/REACT_ARCHITECTURE.md`` §3), so the URL is
    built here instead.
    """
    with SessionLocal() as db:
        rows = (
            db.query(Clip).join(Lecture, Clip.lecture_id == Lecture.id)
            .filter(Lecture.course_id == course_id, Clip.ok == 1)
            .all()
        )
    out: dict = {}
    for clip in rows:
        url = clip_media_url(clip.path, clip.lecture_id)
        if url and clip.concept_name not in out:
            out[clip.concept_name] = url
    return out
