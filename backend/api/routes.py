"""
API routes — the Streamlit frontend talks to the pipeline only through
these, never by importing backend/pipeline/* directly.

Current endpoints:
    POST /lectures            — upload media, kick off background transcription
    GET  /lectures            — list all ingested lectures
    GET  /lectures/{id}       — status + transcript segments + concepts
    POST /lectures/{id}/concepts — run concept extraction (Stage 2, spoken)
"""

import re
import shutil
from datetime import datetime
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
from pydantic import BaseModel, ConfigDict

from backend.models.db import Concept, Lecture, SessionLocal, TranscriptSegment
from backend.pipeline.extract_concepts import extract_spoken_concepts
from backend.pipeline.transcribe import transcribe

router = APIRouter()

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
ALLOWED_EXTENSIONS = {".mp4", ".mp3", ".wav", ".m4a", ".mkv", ".mov", ".webm"}


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    start_s: float
    end_s: float
    text: str


class LectureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: str
    title: str
    status: str
    error: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None


class ConceptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    implicit: bool
    start_s: Optional[float] = None
    end_s: Optional[float] = None


class LectureDetailOut(LectureOut):
    segments: List[SegmentOut] = []
    concepts: List[ConceptOut] = []


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.\- ]", "_", name).strip()


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


@router.post("/lectures", response_model=LectureOut, status_code=201)
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

    background_tasks.add_task(_process_lecture, lecture.id)
    return lecture


@router.get("/lectures", response_model=List[LectureOut])
def list_lectures() -> List[Lecture]:
    with SessionLocal() as db:
        return db.query(Lecture).order_by(Lecture.id).all()


@router.get("/lectures/{lecture_id}", response_model=LectureDetailOut)
def get_lecture(lecture_id: int) -> Lecture:
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            raise HTTPException(status_code=404, detail="Lecture not found")
        _ = lecture.segments  # force-load before session closes
        db.refresh(lecture, ["concepts"])
        return lecture


@router.post("/lectures/{lecture_id}/concepts", response_model=LectureDetailOut)
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

    background_tasks.add_task(_extract_concepts_worker, lecture_id_out)
    with SessionLocal() as db:
        return db.get(Lecture, lecture_id_out)


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
