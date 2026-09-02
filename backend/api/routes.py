"""
API routes — the Streamlit frontend talks to the pipeline only through
these, never by importing backend/pipeline/* directly.

Current endpoints:
    POST /lectures            — upload media, kick off background transcription
    GET  /lectures            — list all ingested lectures
    GET  /lectures/{id}       — status + transcript segments + concepts
    POST /lectures/{id}/concepts — run concept extraction (Stage 2, spoken)
    POST /courses/{id}/graph  — build/persist the per-course prerequisite
                                 graph (Stage 4) in the background
    GET  /courses/{id}/graph  — fetch a course's persisted graph + learner order
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

from backend.models.db import (
    Concept,
    GraphEdge,
    GraphNode,
    Lecture,
    SessionLocal,
    TranscriptSegment,
)
from backend.pipeline.build_graph import ConceptGraph, build_graph_from_pairs
from backend.pipeline.classify_prerequisites import classify_course_pairs
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


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    confidence: float


class CourseGraphOut(BaseModel):
    course_id: str
    nodes: List[str]
    edges: List[GraphEdgeOut] = []
    node_count: int
    edge_count: int
    is_dag: bool
    topological_order: List[str]


class CourseBuildOut(BaseModel):
    status: str
    course_id: str


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


@router.get("/courses/{course_id}/graph", response_model=CourseGraphOut)
def get_course_graph(course_id: str) -> CourseGraphOut:
    """Fetch a course's persisted prerequisite graph and learner order.

    The stored edges/nodes are already acyclic (cycles were broken at build
    time by dropping lowest-confidence edges), so this recomputes the
    topological order from the persisted rows.
    """
    with SessionLocal() as db:
        node_rows = (
            db.query(GraphNode)
            .filter(GraphNode.course_id == course_id)
            .order_by(GraphNode.id)
            .all()
        )
        if not node_rows:
            raise HTTPException(status_code=404, detail="No graph for this course")
        edge_rows = db.query(GraphEdge).filter(GraphEdge.course_id == course_id).all()

    graph = ConceptGraph()
    graph.add_concepts([n.name for n in node_rows])
    for e in edge_rows:
        graph.add_edge(e.source, e.target, e.confidence)
    graph.resolve_cycles()
    return CourseGraphOut(course_id=course_id, **graph.to_dict())


@router.post("/courses/{course_id}/graph", response_model=CourseBuildOut, status_code=202)
def build_course_graph(
    course_id: str, background_tasks: BackgroundTasks
) -> CourseBuildOut:
    """Build (or rebuild) the prerequisite graph for a course in the background.

    Collects the course's extracted concepts, scores candidate pairs with the
    LectureBank-trained classifier (Stage 3), and persists the deduplicated
    nodes + acyclic edges (Stage 4). Rows are replaced per course on re-run,
    so the Stage 7 refinement loop can update the graph safely.
    """
    background_tasks.add_task(_build_course_graph_worker, course_id.strip())
    return CourseBuildOut(status="queued", course_id=course_id.strip())


def _build_course_graph_worker(course_id: str) -> None:
    """Background worker: dedup concept names, score edges, persist per-course."""
    with SessionLocal() as db:
        rows = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.id)
            .all()
        )
        if not rows:
            return
        concepts = [
            {"name": c.name, "start_s": c.start_s, "end_s": c.end_s} for c in rows
        ]
    names = sorted({c["name"] for c in concepts})

    graph = ConceptGraph()
    graph.add_concepts(names)
    try:
        confirmed = classify_course_pairs(concepts)
    except ValueError:
        confirmed = []  # LectureBank absent on this deployment -> nodes-only
    for e in confirmed:
        graph.add_edge(e["a"], e["b"], e["confidence"])
    graph.resolve_cycles()

    with SessionLocal() as db:
        db.query(GraphNode).filter(GraphNode.course_id == course_id).delete()
        db.query(GraphEdge).filter(GraphEdge.course_id == course_id).delete()
        for name in graph.nodes():
            db.add(GraphNode(course_id=course_id, name=name))
        for e in graph.edges():
            db.add(
                GraphEdge(
                    course_id=course_id,
                    source=e["source"],
                    target=e["target"],
                    confidence=e["confidence"],
                )
            )
        db.commit()
