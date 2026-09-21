"""Lecture ingestion endpoints — upload/media lifecycle, concept extraction,
clip cutting. All paths live under /lectures."""

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from backend.api import workers
from backend.api.schemas import (
    ClipBatchOut,
    ClipOut,
    LectureDeleteOut,
    LectureDetailOut,
    LectureOut,
    LectureProgressOut,
)
from backend.models.db import Clip, Concept, Lecture, SessionLocal

router = APIRouter(prefix="/lectures", tags=["lectures"])

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
CLIPS_DIR = REPO_ROOT / "data" / "processed" / "clips"
ALLOWED_EXTENSIONS = {".mp4", ".mp3", ".wav", ".m4a", ".mkv", ".mov", ".webm"}
# Optional upload cap (MiB). Default 2048 MiB to prevent disk-fill DoS.
# Override via LECGAP_MAX_UPLOAD_MB=0 to restore unlimited for local use.
MAX_UPLOAD_MB = int(os.getenv("LECGAP_MAX_UPLOAD_MB", "2048"))


def _safe_filename(name: str) -> str:
    """Sanitize a filename, preventing path traversal attacks.

    - Dots are stripped from the stem (no `../../` traversal).
    - Only the suffix is preserved, normalized to lowercase.
    - After construction the caller must verify the resolved destination
      stays strictly inside DATA_RAW_DIR (see upload_lecture).
    """
    stem = re.sub(r"[^\w\- ]", "_", Path(name).stem).strip() or "upload"
    ext = Path(name).suffix.lower()
    return f"{stem}{ext}"


@router.post("", response_model=LectureOut, status_code=201)
async def upload_lecture(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    title: Optional[str] = Form(None),
    whisper_backend: Optional[str] = Form(None),
) -> Lecture:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    if whisper_backend not in (None, "local", "groq"):
        raise HTTPException(
            status_code=400,
            detail=f"whisper_backend must be 'local' or 'groq', got '{whisper_backend}'",
        )

    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        lecture = Lecture(
            course_id=course_id.strip(),
            title=(title or Path(file.filename).stem).strip(),
            status="uploaded",
        )
        db.add(lecture)
        db.commit()
        db.refresh(lecture)

        dest = DATA_RAW_DIR / _safe_filename(f"lec{lecture.id}_{file.filename}")
        # Path traversal guard: verify resolved path stays inside DATA_RAW_DIR
        try:
            resolved = dest.resolve()
            allowed = DATA_RAW_DIR.resolve()
            if not str(resolved).startswith(str(allowed)):
                db.delete(lecture)
                db.commit()
                raise HTTPException(status_code=400, detail="Invalid filename")
        except HTTPException:
            raise
        except Exception:
            db.delete(lecture)
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid filename")

        written = 0
        with dest.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if MAX_UPLOAD_MB and written > MAX_UPLOAD_MB * 1024 * 1024:
                    out.close()
                    dest.unlink(missing_ok=True)
                    db.delete(lecture)
                    db.commit()
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds LECGAP_MAX_UPLOAD_MB={MAX_UPLOAD_MB} MiB",
                    )
                out.write(chunk)

        lecture.source_path = str(dest)
        db.commit()

    background_tasks.add_task(workers._process_lecture, lecture.id, whisper_backend)
    return lecture


@router.get("", response_model=List[LectureOut])
def list_lectures(limit: int = 500, offset: int = 0) -> List[Lecture]:
    """Lecture list, paginated (M5) — the sidebar/frontend fetches this per
    rerun, so bound the rows returned; defaults stay backward compatible."""
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    with SessionLocal() as db:
        return (
            db.query(Lecture)
            .order_by(Lecture.id)
            .offset(offset)
            .limit(limit)
            .all()
        )


@router.get("/{lecture_id}", response_model=LectureDetailOut)
def get_lecture(lecture_id: int) -> Lecture:
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail="Lecture not found")
        _ = lecture.segments  # force-load before session closes
        db.refresh(lecture, ["concepts"])
        return lecture


@router.get("/{lecture_id}/progress", response_model=LectureProgressOut)
def get_lecture_progress(lecture_id: int) -> LectureProgressOut:
    """Live job progress — the streamlit progress bars poll this while a
    background worker (transcribe / extract / clips) is running."""
    return LectureProgressOut(**workers.get_lecture_progress(lecture_id))


@router.delete("/{lecture_id}", response_model=LectureDeleteOut)
def delete_lecture(lecture_id: int) -> LectureDeleteOut:
    """Delete a lecture: its rows, raw media on disk, and cut clips. When the
    lecture was its course's last one, course-scoped leftovers (graph,
    questions, responses) are purged too so no stale data survives."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found")
        course_id = lecture.course_id
        source_path = lecture.source_path
        db.delete(lecture)  # ORM cascade removes segments/concepts/clips/passages/links
        remaining = (
            db.query(Lecture.id).filter(Lecture.course_id == course_id).first()
        )
        orphaned = remaining is None
        db.commit()

    if source_path:
        try:
            os.remove(source_path)
        except OSError:
            pass
    shutil.rmtree(CLIPS_DIR / str(lecture_id), ignore_errors=True)

    if orphaned:
        workers.purge_course(course_id)

    return LectureDeleteOut(
        deleted=True,
        lecture_id=lecture_id,
        message=f"Lecture {lecture_id} deleted"
        + (" (course data purged)" if orphaned else ""),
    )


@router.post("/{lecture_id}/rerun", response_model=LectureOut)
def rerun_lecture(
    lecture_id: int,
    background_tasks: BackgroundTasks,
    whisper_backend: Optional[str] = None,
) -> Lecture:
    """Re-run transcription for an existing lecture without re-uploading media."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail=f"Lecture {lecture_id} not found")
        if not lecture.source_path or not os.path.exists(lecture.source_path):
            raise HTTPException(
                status_code=400,
                detail=f"Source file for lecture {lecture_id} not found on disk",
            )
        lecture.status = "uploaded"
        lecture.error = None
        db.commit()
        db.refresh(lecture)
        delivered = lecture

    background_tasks.add_task(workers._process_lecture, lecture_id, whisper_backend)
    return delivered


@router.post("/{lecture_id}/concepts", response_model=LectureDetailOut)
def run_concept_extraction(
    lecture_id: int, background_tasks: BackgroundTasks
) -> Lecture:
    """Extract (spoken) concepts for a lecture. Runs in background; results
    appear on GET /lectures/{id} once done. Concept rows are replaced on
    re-run (idempotent, cached LLM calls keep re-runs free)."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail="Lecture not found")
        if lecture.status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Lecture status is '{lecture.status}'; must be 'ready' before extraction",
            )
        lecture_id_out = lecture.id

    background_tasks.add_task(workers._extract_concepts_worker, lecture_id_out)
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id_out)
        _ = lecture.segments  # force-load before session closes
        db.refresh(lecture, ["concepts"])
        return lecture


@router.post("/{lecture_id}/clips", response_model=ClipBatchOut, status_code=202)
def cut_lecture_clips(
    lecture_id: int, background_tasks: BackgroundTasks
) -> ClipBatchOut:
    """Cut one ffmpeg clip per concept with timestamps, in the background.

    Needs a ready lecture with concepts extracted (steps 4-5 in the
    quickstart). Clips are written under data/processed/clips/<lecture_id>/
    and persisted as `clips` rows; re-runs replace the lecture's rows.
    """
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail="Lecture not found")
        if lecture.status != "ready":
            raise HTTPException(
                status_code=409,
                detail=f"Lecture status is '{lecture.status}'; must be 'ready' to cut clips",
            )
        has_concepts = (
            db.query(Concept.id)
            .filter(Concept.lecture_id == lecture_id)
            .first()
            is not None
        )
        if not has_concepts:
            raise HTTPException(
                status_code=409,
                detail="No concepts extracted yet; run POST /lectures/{id}/concepts first",
            )
        lecture_id_out = lecture.id

    background_tasks.add_task(workers._cut_clips_worker, lecture_id_out)
    return ClipBatchOut(lecture_id=lecture_id_out, status="queued")


@router.get("/{lecture_id}/clips", response_model=ClipBatchOut)
def list_lecture_clips(lecture_id: int) -> ClipBatchOut:
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail="Lecture not found")
        rows = (
            db.query(Clip)
            .filter(Clip.lecture_id == lecture_id)
            .order_by(Clip.id)
            .all()
        )
        clips = [ClipOut.model_validate(r) for r in rows]
    return ClipBatchOut(lecture_id=lecture_id, status="ready", clips=clips)