"""Lecture ingestion endpoints — upload/media lifecycle, concept extraction,
clip cutting. All paths live under /lectures."""

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
    LectureOut,
    LectureDetailOut,
)
from backend.models.db import Clip, Concept, Lecture, SessionLocal

router = APIRouter(prefix="/lectures", tags=["lectures"])

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
ALLOWED_EXTENSIONS = {".mp4", ".mp3", ".wav", ".m4a", ".mkv", ".mov", ".webm"}


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", name).strip()


@router.post("", response_model=LectureOut, status_code=201)
async def upload_lecture(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    title: Optional[str] = Form(None),
) -> Lecture:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
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
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)

        lecture.source_path = str(dest)
        db.commit()

    background_tasks.add_task(workers._process_lecture, lecture.id)
    return lecture


@router.get("", response_model=List[LectureOut])
def list_lectures() -> List[Lecture]:
    with SessionLocal() as db:
        return db.query(Lecture).order_by(Lecture.id).all()


@router.get("/{lecture_id}", response_model=LectureDetailOut)
def get_lecture(lecture_id: int) -> Lecture:
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail="Lecture not found")
        _ = lecture.segments  # force-load before session closes
        db.refresh(lecture, ["concepts"])
        return lecture


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