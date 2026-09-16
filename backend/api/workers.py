"""Background workers + shared DB/pipeline helpers — moved out of routes.py.

Holds every long-running job the endpoints schedule (transcription, concept
extraction, clip cutting, course-graph rebuild) plus the cross-endpoint query
helpers. Endpoints stay thin: they validate input, schedule a worker, and read
back rows. Purely server-side — no HTTP logic lives here beyond what the route
layer calls.
"""

from datetime import datetime
from pathlib import Path
from typing import List

from backend.models.db import (
    Clip,
    Concept,
    GraphEdge,
    GraphNode,
    Lecture,
    LectureLink,
    Passage,
    SessionLocal,
    TranscriptSegment,
)
from backend.pipeline.build_graph import ConceptGraph
from backend.pipeline.extract_concepts import extract_spoken_concepts
from backend.pipeline.passages import extract_lecture_structure
from backend.pipeline.refine_timeline import refine_concept_times
from backend.pipeline.segment_clips import cut_concept_clips
from backend.pipeline.transcribe import transcribe
from backend.api.schemas import QuizQuestionOut

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _extract_concepts_worker(lecture_id: int) -> None:
    """Background worker: run the Lecture-Structure pass and persist rows.

    Happy path: `extract_lecture_structure` reads the whole lecture in sliding
    windows and returns passages + flattened concept teach-spans + spoken
    prerequisite links. The worker persists all three (concepts gain their
    `passage_id`; links land in `lecture_links`), then rebuilds the course
    graph. If the WHOLE pass fails (LLM backend down), it falls back to the
    chunk-atomic path (extract_spoken_concepts + refine_concept_times) so a
    user is never stranded — the old path is the rescue rope, not the default.
    """
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            return
        docs = [
            {"start_s": s.start_s, "end_s": s.end_s, "text": s.text}
            for s in lecture.segments
        ]
        course_id = lecture.course_id

    passages: List[dict] = []
    links: List[dict] = []
    try:
        structure = extract_lecture_structure(docs)
        concepts = structure["concepts"]
        passages = structure["passages"]
        links = structure["links"]
    except Exception:  # noqa: BLE001 — whole-pass failure -> old path
        try:
            concepts = extract_spoken_concepts(docs)
            # Stage 2b fallback: pin chunk-stamped spans down to teach-spans.
            concepts = refine_concept_times(concepts, docs)
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
    _rebuild_course_graph(course_id)


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


def _build_course_graph_worker(course_id: str) -> None:
    """Background worker: dedup concept names, score edges, persist per-course.

    No-op when the course has no concept rows yet — the concept-extraction
    worker rebuilds the graph itself once its new concepts are persisted, so a
    caller that fires this before extraction finishes still ends up correct.
    """
    _rebuild_course_graph(course_id.strip())


def _rebuild_course_graph(course_id: str) -> None:
    """Regenerate a course's prerequisite graph from its current concept rows.

    Transcript-first (plan/LECTURE_STRUCTURE.md §4): lecture_links persisted by
    the extraction pass become edges at confidence 0.9 with their verbatim
    evidence (`source_method="transcript"`); the LectureBank classifier then
    fills ONLY pairs the transcript never grounded (`source_method="classifier"`),
    which is where cross-lecture relations and silent jumps live. Cycle
    resolution is unchanged — it drops the lowest-confidence edge on a cycle, so
    transcript edges (0.9) dominate by design.
    Shared by POST /courses/{id}/graph and the concept-extraction worker so
    the graph always reflects the latest extracted concept set regardless of
    call order (the UI fires both requests back-to-back; without this chaining
    the graph request can query an empty Concept table and silently exit).
    Idempotent — existing rows are replaced per course on re-run.
    """
    from backend.pipeline.build_graph import ConceptGraph

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
        lect_ids = [
            row[0]
            for row in db.query(Lecture.id).filter(Lecture.course_id == course_id).all()
        ]
        link_rows = []
        if lect_ids:
            link_rows = (
                db.query(LectureLink)
                .filter(LectureLink.lecture_id.in_(lect_ids))
                .all()
            )
        # one edge per (source, target), keeping the first verbatim evidence
        pair_by: dict = {}
        for r in link_rows:
            key = (r.source_name, r.target_name)
            if key not in pair_by:
                pair_by[key] = r.evidence or None
        link_pairs = [(a, b, ev) for (a, b), ev in pair_by.items()]

    names = sorted({c["name"] for c in concepts})

    # Load the embedding model ONCE (lazily, wherever it is first needed) and
    # share that single instance across concept dedup, the candidate
    # pre-filter, and the classifier fit/predict — previously each stage
    # constructed its own SentenceTransformer, so one graph rebuild printed
    # "Loading weights" three times and paid the load cost 3x.
    from backend.pipeline.classify_prerequisites import PrerequisiteClassifier, \
        classify_course_pairs

    clf = PrerequisiteClassifier()
    graph = ConceptGraph(encoder_fn=clf._get_encoder)
    graph.add_concepts(names)
    g = graph.to_networkx()
    edge_meta: dict = {}
    for a, b, ev in link_pairs:
        a_res, b_res = graph._resolve(a), graph._resolve(b)
        edge_meta[(a_res, b_res)] = ("transcript", ev)
        graph.add_edge(a, b, 0.9)
    try:
        confirmed = classify_course_pairs(concepts, encoder=clf._encoder)
    except ValueError:
        confirmed = []  # LectureBank absent on this deployment -> nodes-only
    for e in confirmed:
        a_res, b_res = graph._resolve(e["a"]), graph._resolve(e["b"])
        if g.has_edge(a_res, b_res):
            continue  # already grounded by the transcript — keep the spoken edge
        graph.add_edge(e["a"], e["b"], e["confidence"])
        edge_meta[(a_res, b_res)] = ("classifier", None)
    graph.resolve_cycles()

    with SessionLocal() as db:
        db.query(GraphNode).filter(GraphNode.course_id == course_id).delete()
        db.query(GraphEdge).filter(GraphEdge.course_id == course_id).delete()
        for name in graph.nodes():
            db.add(GraphNode(course_id=course_id, name=name))
        for e in graph.edges():
            method, evidence = edge_meta.get(
                (e["source"], e["target"]), ("classifier", None)
            )
            db.add(
                GraphEdge(
                    course_id=course_id,
                    source=e["source"],
                    target=e["target"],
                    confidence=e["confidence"],
                    source_method=method,
                    evidence=evidence,
                )
            )
        db.commit()


def _lecture_segments(db, course_id: str) -> List[TranscriptSegment]:
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


def _in_range(
    segments: List[TranscriptSegment],
    concept: Concept,
    margin_s: float = 0.5,
) -> List[TranscriptSegment]:
    """Segments that fall inside a concept's spoken window (+ margin)."""
    if concept.start_s is None:
        return segments
    return [
        s
        for s in segments
        if s.start_s >= concept.start_s - margin_s
        and s.end_s <= concept.end_s + margin_s
    ]


def _question_out(item) -> QuizQuestionOut:
    """Present a stored question with its options in shuffled order."""
    import random

    options = [item.answer] if item.answer else []
    options += [
        d
        for d in (item.distractor_a, item.distractor_b, item.distractor_c)
        if d and d != item.answer
    ]
    rnd = random.Random(f"{item.id}:{item.concept}")
    rnd.shuffle(options)
    return QuizQuestionOut(
        id=item.id,
        concept=item.concept,
        question=item.question,
        options=options,
        distractor_a=item.distractor_a,
        distractor_b=item.distractor_b,
        distractor_c=item.distractor_c,
    )


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