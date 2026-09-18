"""Background workers + shared DB/pipeline helpers — moved out of routes.py.

Holds every long-running job the endpoints schedule (transcription, concept
extraction, clip cutting, course-graph rebuild) plus the cross-endpoint query
helpers. Endpoints stay thin: they validate input, schedule a worker, and read
back rows. Purely server-side — no HTTP logic lives here beyond what the route
layer calls.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import List

from backend.models.db import (
    Clip,
    Concept,
    ConceptItem,
    GraphEdge,
    GraphNode,
    Lecture,
    LectureLink,
    Passage,
    QuizResponse,
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

import threading
import time

REPO_ROOT = Path(__file__).resolve().parents[2]

_LOGGER = logging.getLogger("lecgap.workers")

# One long-lived classifier per process (H4): the MiniLM encoder weights and
# the LectureBank-fitted logistic head construct/fit ONCE and are reused by
# every course-graph rebuild. Previously each rebuild built a fresh
# PrerequisiteClassifier and re-fitted the head on ~42k rows, and re-loaded
# the encoder per stage.
_shared_clf_guard = threading.Lock()
_shared_clf = None


def _get_shared_classifier():
    """Lazily construct (once per process) the shared prerequisite classifier."""
    global _shared_clf
    if _shared_clf is None:
        from backend.pipeline.classify_prerequisites import PrerequisiteClassifier

        with _shared_clf_guard:
            if _shared_clf is None:
                try:
                    _shared_clf = PrerequisiteClassifier()
                except Exception as exc:  # noqa: BLE001 — HF model load is network-dependent
                    raise RuntimeError(
                        f"Classifier model load failed: {type(exc).__name__}: {exc}"
                    ) from exc
    return _shared_clf


def _client_error_message(exc: Exception, context: str = "Pipeline stage") -> str:
    """Sanitize a stage failure for the client (M2).

    Full exception detail and traceback are logged server-side; what lands in
    `lecture.error` (and is returned by GET /lectures[/{id}] / /progress) is a
    generic message — never ffmpeg stderr, temp paths, or Groq internals.
    """
    _LOGGER.exception("%s failed: %s", context, exc)
    return f"{context} failed — see server logs for details."

# Live per-lecture job progress, published by the long-running workers and
# read by GET /lectures/{id}/progress (the Streamlit progress bars poll it).
# Thread-safe (workers run on the request threadpool). Entries are pruned on
# a job's final state (ready/error) so long-lived processes don't leak.
_progress_lock = threading.Lock()
_lecture_progress: dict = {}


def update_lecture_progress(
    lecture_id: int, stage: str, pct: int, detail: str, status: str = "transcribing"
) -> None:
    with _progress_lock:
        entry = _lecture_progress.get(lecture_id)
        if entry is None:
            entry = _lecture_progress[lecture_id] = {"start_time": time.time()}
        entry["stage"] = stage
        entry["pct"] = int(max(0, min(pct, 100)))
        entry["detail"] = detail
        entry["status"] = status
        entry["updated_at"] = time.time()


def _progress_finish(lecture_id: int) -> None:
    """Drop the in-memory entry once a job settles (ready/error)."""
    with _progress_lock:
        _lecture_progress.pop(lecture_id, None)


def get_lecture_progress(lecture_id: int) -> dict:
    """Snapshot of live progress, or a DB-derived fallback once the job ended."""
    with _progress_lock:
        prog = _lecture_progress.get(lecture_id)
        if prog is not None:
            elapsed = time.time() - prog["start_time"]
            return {
                "lecture_id": lecture_id,
                "status": prog.get("status", "transcribing"),
                "stage": prog.get("stage", "working"),
                "progress_pct": prog.get("pct", 0),
                "detail": prog.get("detail", "Processing..."),
                "elapsed_s": round(elapsed, 1),
                "updated_at": datetime.fromtimestamp(
                    prog.get("updated_at", time.time())
                ).astimezone().isoformat(),
            }
    with SessionLocal() as db:
        lec = db.get(Lecture, lecture_id)
        if lec is None:
            status, pct, detail = "not_found", 0, "Lecture not found"
        elif lec.status == "ready":
            status, pct, detail = "ready", 100, "Ready"
        elif lec.status == "error":
            status, pct, detail = "error", 0, lec.error or "Error"
        else:
            status, pct, detail = lec.status, 50, f"Lecture status: {lec.status}"
        return {
            "lecture_id": lecture_id,
            "status": status,
            "stage": status,
            "progress_pct": pct,
            "detail": detail,
            "elapsed_s": 0.0,
            "updated_at": datetime.now().astimezone().isoformat(),
        }


def _process_lecture(lecture_id: int, backend: str = None) -> None:
    """Background worker: transcribe one lecture and persist its segments.

    ``backend`` ("groq"/"local"/None) maps onto transcribe()'s override — the
    upload endpoint surfaces whatever the user picked in the UI.
    """
    update_lecture_progress(
        lecture_id, "initializing", 2, "Starting transcription job...",
        status="transcribing",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _progress_finish(lecture_id)
            return
        lecture.status = "transcribing"
        lecture.error = None
        db.commit()
        source_path = lecture.source_path

    def _on_progress(stage, pct, detail) -> None:
        update_lecture_progress(lecture_id, stage, pct, detail, status="transcribing")

    try:
        segments = transcribe(source_path, backend=backend, progress_callback=_on_progress)
    except Exception as exc:  # noqa: BLE001 — surface any failure on the lecture row
        err_msg = _client_error_message(exc, "Transcription")
        update_lecture_progress(lecture_id, "error", 0, err_msg, status="error")
        with SessionLocal() as db:
            lecture = db.get(Lecture, lecture_id)
            if lecture is not None:
                lecture.status = "error"
                lecture.error = err_msg
                db.commit()
        _progress_finish(lecture_id)
        return

    update_lecture_progress(
        lecture_id, "saving_segments", 97,
        f"Saving {len(segments)} segments to database...", status="transcribing",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _progress_finish(lecture_id)
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
    _progress_finish(lecture_id)


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
    update_lecture_progress(
        lecture_id, "extracting", 10, "Reading transcript and starting structure pass...",
        status="extracting",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _progress_finish(lecture_id)
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
            err_msg = _client_error_message(exc, "Concept extraction")
            update_lecture_progress(lecture_id, "error", 0, err_msg, status="error")
            with SessionLocal() as db:
                lecture = db.get(Lecture, lecture_id)
                if lecture is not None:
                    lecture.status = "error"
                    lecture.error = err_msg
                    db.commit()
            _progress_finish(lecture_id)
            return

    update_lecture_progress(
        lecture_id, "extracting", 70, "Persisting concepts, passages, and spoken links...",
        status="extracting",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _progress_finish(lecture_id)
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
        _rebuild_course_graph(course_id, lecture_id=lecture_id)
    except Exception as exc:  # noqa: BLE001 — graph failure must not strand silently
        err_msg = _client_error_message(exc, "Course-graph rebuild")
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
        _progress_finish(lecture_id)
        return
    update_lecture_progress(
        lecture_id, "ready", 100,
        f"Ready! {len(concepts)} concepts extracted, course graph rebuilt.",
        status="extracting",
    )
    _progress_finish(lecture_id)


def _cut_clips_worker(lecture_id: int) -> None:
    """Background worker: cut one clip per concept and persist the rows."""
    update_lecture_progress(
        lecture_id, "cutting_clips", 5, "Collecting concepts for clip cutting...",
        status="clips",
    )
    with SessionLocal() as db:
        lecture = db.get(Lecture, lecture_id)
        if lecture is None:
            _progress_finish(lecture_id)
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
        _progress_finish(lecture_id)
        return

    out_dir = REPO_ROOT / "data" / "processed" / "clips" / str(lecture_id)

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
        err_msg = _client_error_message(exc, "Clip cutting")
        update_lecture_progress(
            lecture_id, "error", 0, err_msg, status="error"
        )
        with SessionLocal() as db:
            lecture = db.get(Lecture, lecture_id)
            if lecture is not None:
                lecture.status = "error"
                lecture.error = err_msg
                db.commit()
        _progress_finish(lecture_id)
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
    _progress_finish(lecture_id)


def _build_course_graph_worker(course_id: str) -> None:
    """Background worker: dedup concept names, score edges, persist per-course.

    No-op when the course has no concept rows yet — the concept-extraction
    worker rebuilds the graph itself once its new concepts are persisted, so a
    caller that fires this before extraction finishes still ends up correct.
    """
    _rebuild_course_graph(course_id.strip())


def _rebuild_course_graph(course_id: str, lecture_id: int = None) -> None:
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

    ``lecture_id`` ties progress updates to the lecture that triggered the
    rebuild (extraction worker passes its own id so the progress bar moves).
    """
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 60, "Loading shared concept encoder...",
            status="building_graph",
        )
    from backend.pipeline.build_graph import ConceptGraph

    with SessionLocal() as db:
        rows = (
            db.query(Concept)
            .filter(Concept.course_id == course_id)
            .order_by(Concept.id)
            .all()
        )
        if not rows:
            if lecture_id is not None:
                _progress_finish(lecture_id)
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

    # Load/keep the shared embedding model + fitted head (H4): one
    # MiniLM instance serves concept dedup, the candidate pre-filter, and the
    # classifier fit/predict across every rebuild for the process lifetime —
    # previously each rebuild printed "Loading weights" three times, paid the
    # load cost 3x, and re-fit the logistic head on LectureBank per lecture.
    from backend.pipeline.classify_prerequisites import classify_course_pairs

    clf = _get_shared_classifier()
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 75, f"Deduplicating {len(names)} concepts...",
            status="building_graph",
        )
    graph = ConceptGraph(encoder_fn=clf._get_encoder)
    graph.add_concepts(names)
    g = graph.to_networkx()
    edge_meta: dict = {}
    # Only the concepts extracted (and dedup-canonicalised) above are valid
    # nodes. A spoken link whose endpoints were never extracted (LLM
    # hallucination, name variant, cross-lecture reference) is dropped here —
    # letting add_edge auto-create it (build_graph.add_edge) would plant a
    # GraphNode with no Concept row in topo order and remediation.
    known_nodes = set(graph.nodes())
    for a, b, ev in link_pairs:
        a_res, b_res = graph._resolve(a), graph._resolve(b)
        if a_res not in known_nodes or b_res not in known_nodes:
            continue
        edge_meta[(a_res, b_res)] = ("transcript", ev)
        graph.add_edge(a, b, 0.9)
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 85, "Scoring candidate prerequisite pairs...",
            status="building_graph",
        )
    try:
        confirmed = classify_course_pairs(concepts, encoder=clf._encoder)
    except ValueError:
        confirmed = []  # LectureBank absent on this deployment -> nodes-only

    import os
    use_llm_reasoning = os.getenv("LECGAP_LLM_REASONING", "").strip().lower() in {"1", "true", "yes"}
    from backend.pipeline.classify_prerequisites import llm_reasoning_check

    for e in confirmed:
        a_res, b_res = graph._resolve(e["a"]), graph._resolve(e["b"])
        if g.has_edge(a_res, b_res):
            continue  # already grounded by the transcript — keep the spoken edge
        method, reason = "classifier", None
        if use_llm_reasoning:
            try:
                chk = llm_reasoning_check(e["a"], e["b"], prediction=1, confidence=e["confidence"])
                if chk.get("prediction") is False:
                    continue
                reason = chk.get("reason")
                method = "classifier+llm"
            except Exception:
                pass
        graph.add_edge(e["a"], e["b"], e["confidence"])
        edge_meta[(a_res, b_res)] = (method, reason)
    graph.resolve_cycles()

    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 92, "Persisting graph rows...",
            status="building_graph",
        )
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
    if lecture_id is not None:
        update_lecture_progress(
            lecture_id, "building_graph", 98, f"{len(graph.nodes())} nodes, "
            f"{len(graph.edges())} edges persisted.",
            status="building_graph",
        )


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


def purge_course(course_id: str) -> int:
    """Delete every DB row belonging to a course and return lectures removed.

    Covers both lecture-scoped rows (segments, concepts, passages, links,
    clips) and the course-scoped tables that outlive lecture deletion
    (graph nodes/edges, quiz questions, quiz responses) — the exact gap that
    left stale smoke-test courses behind. Idempotent; media files on disk are
    the caller's job (routes own their file layout).
    """
    with SessionLocal() as db:
        lect_ids = [
            row[0]
            for row in db.query(Lecture.id).filter(Lecture.course_id == course_id).all()
        ]
        db.query(QuizResponse).filter(QuizResponse.course_id == course_id).delete(
            synchronize_session=False
        )
        db.query(ConceptItem).filter(ConceptItem.course_id == course_id).delete(
            synchronize_session=False
        )
        db.query(GraphEdge).filter(GraphEdge.course_id == course_id).delete(
            synchronize_session=False
        )
        db.query(GraphNode).filter(GraphNode.course_id == course_id).delete(
            synchronize_session=False
        )
        for lid in lect_ids:
            db.query(Clip).filter(Clip.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(LectureLink).filter(LectureLink.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(Passage).filter(Passage.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(Concept).filter(Concept.lecture_id == lid).delete(
                synchronize_session=False
            )
            db.query(TranscriptSegment).filter(
                TranscriptSegment.lecture_id == lid
            ).delete(synchronize_session=False)
            db.query(Lecture).filter(Lecture.id == lid).delete(
                synchronize_session=False
            )
        db.commit()
        return len(lect_ids)