"""Quiz endpoints — graded MCQ creation, submit/grade, and the remediation
sequence (Stage 6/7). Note: /students paths live here too because remediation
is computed from quiz responses."""

from bisect import bisect_left

from fastapi import APIRouter, Body, HTTPException, Path, Query

from backend.api import graphs, queries
from backend.api.schemas import (
    QuestionFeedbackOut,
    QuizOut,
    QuizSubmitIn,
    QuizSubmitOut,
)
from backend.models.db import (
    Concept,
    ConceptItem,
    Passage,
    QuizResponse,
    SessionLocal,
)
from backend.pipeline.mcq_gen import generate_mcq, local_context
from backend.pipeline.quiz import (
    make_mcq,
    select_remediation_sequence,
    supporting_sentence,
)

router = APIRouter(tags=["quizzes"])


def _watch_entry(item, clips):
    """Serialize one remediation item with its clip path attached."""
    return {
        "concept": item["concept"],
        "failed": item["failed"],
        "clip": clips.get(item["concept"]),
    }


@router.post("/quizzes", response_model=QuizOut, status_code=201)
def create_quiz(
    course_id: str = Body(..., max_length=128, pattern=r"^[\w\-]+$"),
    student_id: str = Body(..., max_length=128, pattern=r"^[\w\-@.]+$"),
) -> QuizOut:
    """Build a graded MCQ quiz from a course's extracted concepts.

    Each question (Stage 6b/6c) is written by the cached LLM from the
    transcript passage where the concept is taught — a real definition plus
    three plausible-but-wrong distractors — falling back to the evidence
    sentence (another concept's spoken description) on any LLM miss. The
    ground-truth option is stored beside the question, and grading happens
    server-side on submit (the probe/self-grade mode of Phase 6 is kept for
    courses that have no transcript evidence yet).
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
        by_name = {c.name: c for c in concepts}

        # Stage 6 grounding (plan/LECTURE_STRUCTURE.md §4): when the concept was
        # extracted by the Lecture-Structure pass its full teaching passage is
        # persisted — the MCQ writer reads that text, not a re-scanned window.
        # Concepts without a passage keep the old local_context fallback.
        # Batch load all passages in one IN query (H6: was one db.get per concept).
        pids = {c.passage_id for c in concepts if c.passage_id is not None}
        passage_text = {
            p.id: p.text
            for p in db.query(Passage).filter(Passage.id.in_(pids)).all()
            if p.text
        }
        passage_ctx = {
            name: passage_text[c.passage_id]
            for name, c in by_name.items()
            if c.passage_id in passage_text
        }

        segments = queries.lecture_segments(db, course_id)
        # H6: the evidence loop below scans the course-wide segment list per
        # concept. Time-sorted segments + a bisect window answer "segments in
        # the concept's window" in O(log n + window) instead of O(course).
        starts = [s.start_s for s in segments]

        def _window(concept, margin_s=0.5):
            """Segments whose span fits inside the concept's window (+ margin),
            found via bisect: start_s >= lo and end_s <= hi."""
            if concept.start_s is None:
                return segments
            lo = concept.start_s - margin_s
            hi = concept.end_s + margin_s
            i = bisect_left(starts, lo)
            out = []
            while i < len(segments) and starts[i] <= hi:
                if segments[i].end_s <= hi:
                    out.append(segments[i])
                i += 1
            return out

        # one distinct evidence sentence per concept: once a sentence is used
        # as one concept's answer it is skipped for the rest, so concepts whose
        # names never appear verbatim don't all collapse onto one "longest"
        # segment (that made answers identical across questions).
        used: set = set()
        evidence: dict = {}
        for name in names:
            ev = supporting_sentence(
                name, _window(by_name[name]), skip=used,
            )
            if ev is None:
                ev = supporting_sentence(name, segments, skip=used)
            if ev is not None:
                used.add(ev)
            evidence[name] = ev

    # learner order from the graph if present, else alphabetic
    data = graphs.course_graph(course_id)
    if data is not None:
        order = data["topological_order"]
        names = [n for n in order if n in set(names)] or names

    # Stage 6c: prefer a cached LLM-written MCQ (real definitions + plausible
    # distractors) over the evidence sentence. Network calls happen outside any
    # DB session; any miss falls back to the pure evidence path, so LLM
    # generation can only upgrade a quiz, never break it.
    def _make_one(concept_name: str):
        q = None
        ctx = passage_ctx.get(concept_name) or local_context(segments, by_name.get(concept_name))
        if ctx:
            try:
                q = generate_mcq(concept_name, ctx)
            except Exception:
                q = None
        if not q:
            q = make_mcq(
                concept_name,
                evidence[concept_name],
                [(o, evidence[o]) for o in names if o != concept_name],
            )
        return concept_name, q

    plan: dict = {}
    if len(names) <= 1:
        for name in names:
            _, q = _make_one(name)
            plan[name] = q
    else:
        from concurrent.futures import ThreadPoolExecutor
        workers_count = min(6, len(names))
        with ThreadPoolExecutor(max_workers=workers_count) as pool:
            for concept_name, q in pool.map(_make_one, names):
                plan[concept_name] = q

    with SessionLocal() as db:
        db.query(ConceptItem).filter(ConceptItem.course_id == course_id).delete()
        new_ids = []
        for i, name in enumerate(names):
            q = plan[name]
            item = ConceptItem(
                course_id=course_id,
                concept=name,
                question=q["question"],
                answer=q["answer"],
                order=i,
                explanation=q.get("explanation"),
            )
            distractors = [o for o in q["options"] if o != q["answer"]]
            distractors += [None] * (3 - len(distractors))
            rationale_by_option = q.get("rationale") or {}
            item.distractor_a, item.distractor_b, item.distractor_c = distractors[:3]
            item.rationale_a = rationale_by_option.get(distractors[0])
            item.rationale_b = rationale_by_option.get(distractors[1])
            item.rationale_c = rationale_by_option.get(distractors[2])
            db.add(item)
            db.flush()
            new_ids.append(item.id)
        db.commit()
        rows = db.query(ConceptItem).filter(ConceptItem.id.in_(new_ids)).all()

    rows.sort(key=lambda r: r.order)
    return QuizOut(
        quiz_id=rows[0].id if rows else 0,
        course_id=course_id,
        student_id=student_id,
        questions=[queries.question_out(r) for r in rows],
    )


@router.post("/quizzes/submit", response_model=QuizSubmitOut)
def submit_quiz(payload: QuizSubmitIn) -> QuizSubmitOut:
    """Record a student's answers and return their remediation sequence.

    Failed concepts feed the prerequisite graph (Stage 4) to produce the
    dependency-ordered watch list. Re-submitting for the same student+course
    appends with `attempt` incremented per distinct question.
    """
    with SessionLocal() as db:
        feedback = []
        for a in payload.answers:
            quest = db.get(ConceptItem, a.question_id)
            if quest is None:
                raise HTTPException(status_code=404,
                                    detail=f"Question {a.question_id} not found")
            if quest.course_id != payload.course_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Question {a.question_id} belongs to course "
                           f"{quest.course_id!r}, not {payload.course_id!r}",
                )
            # server-side grading: the ground-truth option is stored with the
            # question. The client only ever reports what it *selected*; a
            # question without a stored key grades as wrong (no flag from the
            # client is trusted — that would defeat the quiz and pollute the
            # remediation/heatmap signals).
            if quest.answer is not None:
                correct = a.selected == quest.answer
            else:
                correct = False
            # post-submit feedback: why the right answer is right, and if the
            # student picked a distractor, why that specific option is wrong.
            rationale = None
            if not correct and quest.answer is not None:
                for col, rat in ((quest.distractor_a, quest.rationale_a),
                                 (quest.distractor_b, quest.rationale_b),
                                 (quest.distractor_c, quest.rationale_c)):
                    if a.selected == col:
                        rationale = rat
                        break
            feedback.append(
                QuestionFeedbackOut(
                    question_id=a.question_id,
                    concept=quest.concept,
                    correct=correct,
                    selected=a.selected,
                    answer=quest.answer,
                    explanation=quest.explanation,
                    rationale=rationale,
                )
            )
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
                    correct=int(correct),
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

    data = graphs.course_graph(payload.course_id)
    graph_dict = data if data is not None else {
        "edges": [], "topological_order": sorted({c.concept for c in responses})}

    clips = queries.clips_by_concept(payload.course_id)
    seq = select_remediation_sequence(graph_dict, failed)
    # submit echoes the full dependency chain (every item in learner order);
    # the /students remediation endpoint prunes to what is actually watchable.
    watch = [_watch_entry(item, clips) for item in seq]

    return QuizSubmitOut(
        quiz_id=payload.answers[0].question_id if payload.answers else 0,
        student_id=payload.student_id,
        score=score,
        total=total,
        remediation=watch,
        feedback=feedback,
    )


@router.get("/students/{student_id}/remediation", response_model=QuizSubmitOut)
def get_remediation(
    student_id: str = Path(..., max_length=128, pattern=r"^[\w\-@.]+$"),
    course_id: str = Query(..., max_length=128, pattern=r"^[\w\-]+$"),
) -> QuizSubmitOut:
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

    data = graphs.course_graph(course_id)
    graph_dict = data if data is not None else {
        "edges": [], "topological_order": sorted({r.concept for r in responses})}

    clips = queries.clips_by_concept(course_id)
    seq = select_remediation_sequence(graph_dict, failed)
    # remediation is a *watch* list: only concepts the student actually failed
    # plus anything upstream that has a clip to watch — unlike the post-submit
    # echo, which returns the whole learner chain.
    watch = [
        _watch_entry(item, clips) for item in seq
        if item["failed"] or item["concept"] in clips
    ]

    return QuizSubmitOut(
        quiz_id=question_id,
        student_id=student_id,
        score=score,
        total=total,
        remediation=watch,
    )