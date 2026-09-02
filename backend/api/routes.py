"""
API routes — the Streamlit frontend talks to the pipeline only through
these, never by importing backend/pipeline/* directly.

Current endpoints:
    POST /lectures            — upload media, kick off background transcription
    GET  /lectures            — list all ingested lectures
    GET  /lectures/{id}       — status + transcript segments + concepts
    POST /lectures/{id}/concepts — run concept extraction (Stage 2, spoken)
    POST /lectures/{id}/clips — cut one ffmpeg clip per concept (Stage 5)
    GET  /lectures/{id}/clips — list a lecture's cut clips
    POST /courses/{id}/graph  — build/persist the per-course prerequisite
                                 graph (Stage 4) in the background
    GET  /courses/{id}/graph  — fetch a course's persisted graph + learner order
    POST /quizzes             — make a quiz from a course's concepts (Stage 6)
    POST /quizzes/{id}/submit — record a student's answers + get remediation
    GET  /courses/{id}/stats  — confusion heatmap + divergence (Stage 8)
"""

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict

from backend.models.db import (
    Clip,
    Concept,
    ConceptItem,
    GraphEdge,
    GraphNode,
    Lecture,
    QuizResponse,
    SessionLocal,
    TranscriptSegment,
)
from backend.pipeline.build_graph import ConceptGraph
from backend.pipeline.extract_concepts import extract_spoken_concepts
from backend.pipeline.quiz import select_remediation_sequence
from backend.pipeline.segment_clips import cut_concept_clips
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


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    concept_name: str
    start_s: float
    end_s: float
    path: str
    ok: bool
    error: Optional[str] = None


class ClipBatchOut(BaseModel):
    lecture_id: int
    status: str
    clips: List[ClipOut] = []


class QuizQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    concept: str
    question: str
    distractor_a: Optional[str] = None
    distractor_b: Optional[str] = None
    distractor_c: Optional[str] = None


class QuizOut(BaseModel):
    quiz_id: int
    course_id: str
    student_id: str
    questions: List[QuizQuestionOut] = []


class QuizAnswerIn(BaseModel):
    question_id: int
    selected: Optional[str] = None
    correct: bool
    latency_s: Optional[float] = None


class QuizSubmitIn(BaseModel):
    course_id: str
    student_id: str
    answers: List[QuizAnswerIn]


class WatchItemOut(BaseModel):
    concept: str
    failed: bool
    clip: Optional[str] = None


class QuizSubmitOut(BaseModel):
    quiz_id: int
    student_id: str
    score: int
    total: int
    remediation: List[WatchItemOut] = []


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
        lecture = db.get(Lecture, lecture_id_out)
        _ = lecture.segments  # force-load before session closes
        db.refresh(lecture, ["concepts"])
        return lecture


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


@router.post("/lectures/{lecture_id}/clips", response_model=ClipBatchOut,
             status_code=202)
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

    background_tasks.add_task(_cut_clips_worker, lecture_id_out)
    return ClipBatchOut(lecture_id=lecture_id_out, status="queued")


@router.get("/lectures/{lecture_id}/clips", response_model=ClipBatchOut)
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


def _cut_clips_worker(lecture_id: int) -> None:
    """Background worker: cut one clip per concept and persist the rows."""
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
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

    out_dir = REPO_ROOT / "data" / "processed" / "clips" / str(lecture_id)
    results = cut_concept_clips(str(media_path) if media_path else "", concepts, out_dir)

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
    graph.add_concepts_verbatim([n.name for n in node_rows])  # stored names are canonical
    for e in edge_rows:
        graph.add_edge(e.source, e.target, e.confidence)
    graph.resolve_cycles()
    return CourseGraphOut(course_id=course_id, **graph.to_dict())


def _course_graph_dict(course_id: str) -> dict:
    """Course graph as plain dict {edges, topological_order} for pipeline helpers."""
    out = get_course_graph(course_id)
    return {
        "edges": [{"source": e.source, "target": e.target,
                   "confidence": e.confidence} for e in out.edges],
        "topological_order": out.topological_order,
    }


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
    from backend.pipeline import classify_prerequisites

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
        confirmed = classify_prerequisites.classify_course_pairs(concepts)
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


@router.post("/quizzes", response_model=QuizOut, status_code=201)
def create_quiz(course_id: str = Body(...), student_id: str = Body(...)) -> QuizOut:
    """Build a quiz from a course's extracted concepts.

    Questions are generated from the concepts (a simple probe per concept);
    future work replaces the probe template with an LLM-generated question
    per concept (no extra tables needed — ConceptItem already holds them).
    """
    with SessionLocal() as db:
        concepts = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.id)
            .all()
        )
        if not concepts:
            raise HTTPException(status_code=404, detail="No concepts for course")
        names = sorted({c.name for c in concepts})

    # learners order from the graph if present, else alphabetic
    try:
        graph = get_course_graph(course_id)
        order = graph.topological_order
        names = [n for n in order if n in set(names)] or names
    except HTTPException:
        pass

    with SessionLocal() as db:
        db.query(ConceptItem).filter(ConceptItem.course_id == course_id).delete()
        new_ids = []
        for i, name in enumerate(names):
            item = ConceptItem(
                course_id=course_id,
                concept=name,
                question=(f"Which statement about '{name}' is correct?"),
                order=i,
            )
            db.add(item)
            db.flush()
            new_ids.append(item.id)
        db.commit()
        rows = db.query(ConceptItem).filter(ConceptItem.id.in_(new_ids)).all()

    return QuizOut(
        quiz_id=rows[0].id if rows else 0,
        course_id=course_id,
        student_id=student_id,
        questions=[QuizQuestionOut.model_validate(r) for r in sorted(rows, key=lambda r: r.order)],
    )


@router.post("/quizzes/submit", response_model=QuizSubmitOut)
def submit_quiz(payload: QuizSubmitIn) -> QuizSubmitOut:
    """Record a student's answers and return their remediation sequence.

    Failed concepts feed the prerequisite graph (Stage 4) to produce the
    dependency-ordered watch list. Re-submitting for the same student+course
    appends with `attempt` incremented per distinct question.
    """
    with SessionLocal() as db:
        for a in payload.answers:
            quest = db.get(ConceptItem, a.question_id)
            if quest is None:
                raise HTTPException(status_code=404,
                                    detail=f"Question {a.question_id} not found")
            prev = (
                db.query(QuizResponse)
                .filter(
                    QuizResponse.course_id == payload.course_id,
                    QuizResponse.student_id == payload.student_id,
                    QuizResponse.question_id == a.question_id,
                )
                .count()
            )
            db.add(
                QuizResponse(
                    course_id=payload.course_id,
                    student_id=payload.student_id,
                    question_id=a.question_id,
                    concept=quest.concept,
                    selected=a.selected,
                    correct=int(a.correct),
                    latency_s=a.latency_s,
                    attempt=prev + 1,
                )
            )
        db.commit()

    # return the remediation computed from this (now-persisted) submission
    with SessionLocal() as db:
        responses = (
            db.query(QuizResponse)
            .filter(
                QuizResponse.course_id == payload.course_id,
                QuizResponse.student_id == payload.student_id,
            )
            .order_by(QuizResponse.id)
            .all()
        )
        score = sum(r.correct for r in responses)
        total = len(responses)
        failed = sorted({r.concept for r in responses if not r.correct})

    try:
        graph_dict = _course_graph_dict(payload.course_id)
    except HTTPException:
        graph_dict = {"edges": [], "topological_order": sorted(
            {c.concept for c in responses})}

    clips = _clips_by_concept(payload.course_id)
    seq = select_remediation_sequence(graph_dict, failed)
    watch = [
        {
            "concept": item["concept"],
            "failed": item["failed"],
            "clip": clips.get(item["concept"]),
        }
        for item in seq
    ]
    return QuizSubmitOut(
        quiz_id=payload.answers[0].question_id if payload.answers else 0,
        student_id=payload.student_id,
        score=score,
        total=total,
        remediation=watch,
    )


@router.get("/students/{student_id}/remediation", response_model=QuizSubmitOut)
def get_remediation(student_id: str, course_id: str) -> QuizSubmitOut:
    """Dependency-ordered remediation for a student's latest quiz on a course.

    Failed concepts (= wrong answers) are lifted with everything upstream of
    them from the course's prerequisite graph, ordered so prerequisites are
    watched/studied first. Clips (when cut) are attached for playback.
    """
    with SessionLocal() as db:
        qid = (
            db.query(QuizResponse.question_id)
            .filter(
                QuizResponse.course_id == course_id,
                QuizResponse.student_id == student_id,
            )
            .order_by(QuizResponse.id.desc())
            .first()
        )
        if qid is None:
            raise HTTPException(status_code=404, detail="No quiz responses for student/course")
        question_id = qid[0]

        question = db.get(ConceptItem, question_id)
        responses = (
            db.query(QuizResponse)
            .filter(
                QuizResponse.course_id == course_id,
                QuizResponse.student_id == student_id,
            )
            .order_by(QuizResponse.id)
            .all()
        )
        score = sum(r.correct for r in responses)
        total = len(responses)
        failed = sorted({r.concept for r in responses if not r.correct})

    try:
        graph_dict = _course_graph_dict(course_id)
    except HTTPException:
        graph_dict = {"edges": [], "topological_order": sorted(
            {r.concept for r in responses})}

    clips = _clips_by_concept(course_id)
    seq = select_remediation_sequence(graph_dict, failed)
    watch = []
    for item in seq:
        if item["failed"] or item["concept"] in clips:
            watch.append({
                "concept": item["concept"],
                "failed": item["failed"],
                "clip": clips.get(item["concept"]),
            })

    return QuizSubmitOut(
        quiz_id=question_id,
        student_id=student_id,
        score=score,
        total=total,
        remediation=watch,
    )


@router.get("/courses/{course_id}/stats")
def course_stats(course_id: str) -> dict:
    """Stage 8 — confusion heatmap + taught-vs-learned divergence.

    Heatmap: per concept, wrong-answer rate (0..1) across students (optionally
    bucketed by attempt — a single first-attempt number here, extendable).
    Divergence: index of each concept in the ORDER TAUGHT (lecture sequence,
    i.e. earliest concept timestamp) vs. the ORDER the learned graph says it
    should be LEARNED (topological). Concepts with a big gap are the
    divergence view.
    """
    with SessionLocal() as db:
        rows = (
            db.query(QuizResponse)
            .filter(QuizResponse.course_id == course_id)
            .all()
        )
        concepts = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.start_s)
            .all()
        )

    per_concept: dict = {}
    for r in rows:
        per_concept.setdefault(r.concept, [0, 0])
        per_concept[r.concept][1] += 1
        if not r.correct:
            per_concept[r.concept][0] += 1

    # order taught = earliest mention (start_s) of each concept in lectures
    taught_order = []
    seen = set()
    for c in concepts:
        if c.name not in seen:
            seen.add(c.name)
            taught_order.append(c.name)

    try:
        learned_order = get_course_graph(course_id).topological_order
    except HTTPException:
        learned_order = taught_order

    heatmap = [
        {"concept": name, "wrong": wrong, "attempts": total,
         "rate": (wrong / total) if total else 0.0}
        for name, (wrong, total) in per_concept.items()
    ]
    heatmap.sort(key=lambda x: -x["rate"])

    divergence = []
    for name in set(taught_order) | set(learned_order):
        ti = taught_order.index(name) if name in taught_order else None
        li = learned_order.index(name) if name in learned_order else None
        if ti is not None and li is not None:
            divergence.append(
                {"concept": name, "taught_idx": ti, "learned_idx": li,
                 "gap": li - ti}
            )
    divergence.sort(key=lambda x: -abs(x["gap"]))

    return {
        "course_id": course_id,
        "heatmap": heatmap,
        "divergence": divergence,
        "taught_order": taught_order,
        "learned_order": learned_order,
    }


def _clips_by_concept(course_id: str) -> dict:
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
