"""Stage 5 job — cut one clip per concept and persist the rows."""

import logging
import shutil

from backend.api.jobs.common import (
    PIPELINE_SEMAPHORE,
    REPO_ROOT,
    client_error_message,
)
from backend.api.jobs.progress import _finish, job_scope, update_lecture_progress
from backend.config import CLIPS_BASE_DIR
from backend.models.db import Clip, Lecture, SessionLocal
from backend.pipeline.segment_clips import cut_concept_clips

_log = logging.getLogger("lecgap.jobs.clips")


def cut_clips_worker(lecture_id: int, job_id: int = None) -> None:
    """Background worker: cut one clip per concept and persist the rows."""
    with job_scope(job_id), PIPELINE_SEMAPHORE:
        _cut_clips_worker(lecture_id)


def _cut_clips_worker(lecture_id: int) -> None:
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

    # ------------------------------------------------------------------ purge
    # Delete stale DB rows AND stale files on disk *before* writing anything
    # new.  This is the data-poisoning guard: without it a re-run leaves old
    # .mp4 files on disk even after the DB rows are replaced, so any consumer
    # that resolves paths directly (media player, static server) would serve
    # a superseded clip.
    #
    # Doing the purge BEFORE the ffmpeg run means a crash mid-cut leaves an
    # empty directory — not a mix of old and new clips.  The DB delete is also
    # moved here (before the run) so rows and files are always in sync:
    # either both gone (during the run) or both present (after commit).
    update_lecture_progress(
        lecture_id, "cutting_clips", 7, "Purging stale clips before re-cut...",
        status="clips",
    )
    with SessionLocal() as db:
        deleted_rows = db.query(Clip).filter(Clip.lecture_id == lecture_id).delete()
        db.commit()
    _log.info("lecture %d: purged %d stale clip row(s) from DB", lecture_id, deleted_rows)

    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
        _log.info("lecture %d: removed stale clip directory %s", lecture_id, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # ---------------------------------------------------------------- /purge

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