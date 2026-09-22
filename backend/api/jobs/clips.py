"""Stage 5 job — cut one clip per concept and persist the rows."""

from backend.api.jobs.common import REPO_ROOT, client_error_message
from backend.api.jobs.progress import _finish, update_lecture_progress
from backend.config import CLIPS_BASE_DIR
from backend.models.db import Clip, Lecture, SessionLocal
from backend.pipeline.segment_clips import cut_concept_clips


def cut_clips_worker(lecture_id: int) -> None:
    """Background worker: cut one clip per concept and persist the rows."""
    update_lecture_progress(
        lecture_id, "cutting_clips", 5, "Collecting concepts for clip cutting...",
        status="clips",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _finish(lecture_id)
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

    if not concepts:
        update_lecture_progress(
            lecture_id, "ready", 100, "No concepts to cut.", status="clips"
        )
        _finish(lecture_id)
        return

    out_dir = CLIPS_BASE_DIR / str(lecture_id)

    def _on_clip_done(done: int, total: int) -> None:
        update_lecture_progress(
            lecture_id, "cutting_clips", 10 + int(80 * done / total),
            f"Cutting clip {done} of {total}: {REPO_ROOT.name}/data/processed/clips/{lecture_id}/",
            status="clips",
        )

    results = []
    try:
        results = cut_concept_clips(
            str(media_path) if media_path else "", concepts, out_dir,
            on_done=_on_clip_done,
        )
    except Exception as exc:  # noqa: BLE001 — a bad concept must not strand the lecture
        err_msg = client_error_message(exc, "Clip cutting")
        update_lecture_progress(
            lecture_id, "error", 0, err_msg, status="error"
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
        lecture_id, "saving_clips", 90, "Persisting clip rows...", status="clips"
    )
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
    update_lecture_progress(
        lecture_id, "ready", 100,
        f"Done! {sum(1 for r in results if r.get('ok'))} clips cut.",
        status="clips",
    )
    _finish(lecture_id)