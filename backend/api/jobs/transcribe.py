"""Stage 1 job — transcribe one lecture and persist its transcript segments."""

from datetime import datetime

from backend.api.jobs.common import PIPELINE_SEMAPHORE, client_error_message
from backend.api.jobs.progress import _finish, update_lecture_progress
from backend.models.db import Lecture, SessionLocal, TranscriptSegment
from backend.pipeline.transcribe import transcribe


def process_lecture(lecture_id: int, backend: str = None) -> None:
    """Background worker: transcribe one lecture and persist its segments.

    ``backend`` ("groq"/"local"/None) maps onto transcribe()'s override — the
    upload endpoint surfaces whatever the user picked in the UI.

    Concurrency-throttled by PIPELINE_SEMAPHORE to prevent OOM/CPU exhaustion.
    """
    with PIPELINE_SEMAPHORE:
        _process_lecture_inner(lecture_id, backend)


def _process_lecture_inner(lecture_id: int, backend: str = None) -> None:
    update_lecture_progress(
        lecture_id, "initializing", 2, "Starting transcription job...",
        status="transcribing",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _finish(lecture_id)
            return
        lecture.status = "transcribing"
        lecture.error = None
        db.commit()
        source_path = lecture.source_path

    def _on_progress(stage, pct, detail) -> None:
        update_lecture_progress(lecture_id, stage, pct, detail, status="transcribing")

    def _on_duration(duration_s) -> None:
        update_lecture_progress(
            lecture_id, "probing", 5,
            f"Probing audio duration with ffprobe... {duration_s:.0f}s",
            status="transcribing", duration_s=duration_s,
        )

    try:
        segments = transcribe(
            source_path, backend=backend, progress_callback=_on_progress,
            duration_hook=_on_duration,
        )
    except Exception as exc:  # noqa: BLE001 — surface any failure on the lecture row
        err_msg = client_error_message(exc, "Transcription")
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
        lecture_id, "saving_segments", 97,
        f"Saving {len(segments)} segments to database...", status="transcribing",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _finish(lecture_id)
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
    update_lecture_progress(
        lecture_id, "ready", 100,
        f"Ready! {len(segments)} transcript segments processed.", status="ready",
    )
    _finish(lecture_id)