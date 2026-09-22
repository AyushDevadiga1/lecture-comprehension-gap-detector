"""Stage 2 job — run the Lecture-Structure pass and persist its rows.

Happy path: `extract_lecture_structure` reads the whole lecture in sliding
windows and returns passages + flattened concept teach-spans + spoken
prerequisite links. The worker persists all three (concepts gain their
`passage_id`; links land in `lecture_links`), then rebuilds the course
graph. If the WHOLE pass fails (LLM backend down), it falls back to the
chunk-atomic path (extract_spoken_concepts + refine_concept_times) so a
user is never stranded — the old path is the rescue rope, not the default.
"""

from typing import List

from backend.api.jobs.common import client_error_message
from backend.api.jobs.graph import rebuild_course_graph
from backend.api.jobs.progress import _finish, update_lecture_progress
from backend.models.db import Concept, Lecture, LectureLink, Passage, SessionLocal
from backend.pipeline.extract_concepts import extract_spoken_concepts
from backend.pipeline.passages import extract_lecture_structure
from backend.pipeline.refine_timeline import refine_concept_times


def extract_concepts_worker(lecture_id: int) -> None:
    """Background worker: run the Lecture-Structure pass and persist rows."""
    update_lecture_progress(
        lecture_id, "extracting", 10, "Reading transcript and starting structure pass...",
        status="extracting",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _finish(lecture_id)
            return
        docs = [
            {"start_s": s.start_s, "end_s": s.end_s, "text": s.text}
            for s in lecture.segments
        ]
        course_id = lecture.course_id

    passages: List[dict] = []
    links: List[dict] = []
    try:
        update_lecture_progress(
            lecture_id, "extracting", 25, "Running structure pass (LLM)...",
            status="extracting",
        )
        structure = extract_lecture_structure(docs)
        concepts = structure["concepts"]
        passages = structure["passages"]
        links = structure["links"]
    except Exception:  # noqa: BLE001 — whole-pass failure -> old path
        update_lecture_progress(
            lecture_id, "extracting", 30,
            "Structure pass failed — falling back to chunk-atomic concept extraction.",
            status="extracting",
        )
        try:
            concepts = extract_spoken_concepts(docs)
            # Stage 2b fallback: pin chunk-stamped spans down to teach-spans.
            concepts = refine_concept_times(concepts, docs)
        except Exception as exc:  # noqa: BLE001 — any failure is fine to surface
            err_msg = client_error_message(exc, "Concept extraction")
            update_lecture_progress(lecture_id, "error", 0, err_msg, status="error")
            with SessionLocal() as db:
                lecture = db.get(Lecture, lecture_id)
                if lecture is not None:
                    lecture.status = "error"
                    lecture.error = err_msg
                    db.commit()
            _finish(lecture_id)
            return

    update_lecture_progress(
        lecture_id, "extracting", 70, "Persisting concepts, passages, and spoken links...",
        status="extracting",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _finish(lecture_id)
            return
        lecture.error = None  # a success supersedes any earlier failed run
        db.query(Concept).filter(Concept.lecture_id == lecture_id).delete()
        db.query(LectureLink).filter(LectureLink.lecture_id == lecture_id).delete()
        db.query(Passage).filter(Passage.lecture_id == lecture_id).delete()
        passage_id_of: dict = {}
        for i, p in enumerate(passages):
            row = Passage(
                lecture_id=lecture_id,
                idx=i,
                title=p["title"],
                kind=p.get("kind", "explain"),
                start_s=p["start_s"],
                end_s=p["end_s"],
                summary=p.get("summary") or None,
                text=p.get("text") or None,
            )
            db.add(row)
            db.flush()
            passage_id_of[i] = row.id
        for c in concepts:
            db.add(
                Concept(
                    course_id=course_id,
                    lecture_id=lecture_id,
                    passage_id=passage_id_of.get(c.get("passage_index")),
                    name=c["name"],
                    source=c.get("source", "spoken"),
                    implicit=int(c["implicit"]),
                    start_s=c.get("start_s"),
                    end_s=c.get("end_s"),
                )
            )
        for l in links:
            db.add(
                LectureLink(
                    lecture_id=lecture_id,
                    source_name=l["from"],
                    target_name=l["to"],
                    confidence=0.9,
                    evidence=l.get("evidence") or None,
                )
            )
        db.commit()

    # Stage 3/4 chained server-side: rebuilding the course graph here — after
    # the fresh concepts are persisted — closes the UI race where a parallel
    # POST /courses/{id}/graph queries an empty Concept table and silently
    # exits. Idempotent, so an explicit graph build is harmless either way.
    update_lecture_progress(
        lecture_id, "building_graph", 75, "Rebuilding course prerequisite graph...",
        status="extracting",
    )
    try:
        rebuild_course_graph(course_id, lecture_id=lecture_id)
    except Exception as exc:  # noqa: BLE001 — graph failure must not strand silently
        err_msg = client_error_message(exc, "Course-graph rebuild")
        update_lecture_progress(
            lecture_id, "error", 0,
            f"Concepts saved, but course-graph rebuild failed: {err_msg}",
            status="error",
        )
        with SessionLocal() as db:
            lecture = db.get(Lecture, lecture_id)
            if lecture is not None:
                lecture.status = "error"
                lecture.error = err_msg
                db.commit()
        _finish(lecture_id)
        return
    update_lecture_progress(
        lecture_id, "ready", 100,
        f"Ready! {len(concepts)} concepts extracted, course graph rebuilt.",
        status="extracting",
    )
    _finish(lecture_id)