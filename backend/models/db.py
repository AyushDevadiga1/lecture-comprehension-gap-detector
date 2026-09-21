"""
SQLite persistence layer — sits behind the API, never touched directly by
the frontend (see plan/ARCHITECTURE.md, "Decoupled architecture").

Tables are added incrementally as each phase actually needs to persist
something — not speculatively:

    Phase 1:  lectures, transcript_segments
    Phase 2:  llm_cache (prompt-hash keyed; quota protection), concepts
    Phase 4:  graph_nodes, graph_edges (per-course prerequisite graph)
    Phase 5:  clips (one ffmpeg cut per concept, per lecture)
    Phase 6:  quiz_questions, quiz_responses (student quiz loop)
    Phase 9:  passages, lecture_links (Lecture-Structure pass, plan/LECTURE_STRUCTURE.md)
    Phase 8:  quiz_responses aggregates power the faculty dashboard
    Later:    students, refinement_log

Lecture.status lifecycle: uploaded -> transcribing -> ready | error
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    event,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "lecgap.db"
DATABASE_URL = os.getenv("LECGAP_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

# Background workers + API threads write concurrently; WAL + a busy timeout
# keep "database is locked" out of the picture (long jobs no longer block
# /health and friends while a graph rebuild or segmentation is writing).
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
    if not DATABASE_URL.startswith("sqlite"):
        return
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:  # noqa: BLE001 — a pragma failure must not kill boot
        pass
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Lecture(Base):
    __tablename__ = "lectures"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    source_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="uploaded")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    segments = relationship(
        "TranscriptSegment",
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.idx",
    )

    concepts = relationship(
        "Concept",
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="Concept.id",
    )

    clips = relationship(
        "Clip",
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="Clip.id",
    )

    passages = relationship(
        "Passage",
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="Passage.idx",
    )

    lecture_links = relationship(
        "LectureLink",
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="LectureLink.id",
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    idx = Column(Integer, nullable=False)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    text = Column(Text, nullable=False)

    lecture = relationship("Lecture", back_populates="segments")


class LLMCache(Base):
    __tablename__ = "llm_cache"

    key = Column(String, primary_key=True)
    backend = Column(String, nullable=False)
    model = Column(String, nullable=False)
    response_text = Column(Text, nullable=False)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Concept(Base):
    __tablename__ = "concepts"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    passage_id = Column(Integer, ForeignKey("passages.id"), nullable=True)
    name = Column(String, nullable=False)
    source = Column(String, nullable=False, default="spoken")
    implicit = Column(Integer, nullable=False, default=0)
    start_s = Column(Float, nullable=True)
    end_s = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    lecture = relationship("Lecture", back_populates="concepts")


class Passage(Base):
    """A coherent teaching unit recovered by the Lecture-Structure pass (§3,
    plan/LECTURE_STRUCTURE.md). `text` is the joined transcript excerpt for the
    passage's span — quiz writing and clip grounding read it directly instead
    of re-scanning tiny segment windows. Re-running extraction replaces a
    lecture's rows as a set.
    """

    __tablename__ = "passages"

    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    idx = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="explain")
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    summary = Column(Text, nullable=True)
    text = Column(Text, nullable=True)

    lecture = relationship("Lecture", back_populates="passages")


class LectureLink(Base):
    """A prerequisite relation SPOKEN in a lecture, with verbatim evidence.

    Source of truth for transcript-first graph edges (confidence 0.9 in the
    merged graph). `confidence` stays on the row so the classifier-fallback
    merge in _rebuild_course_graph can weigh re-adding variants.
    """

    __tablename__ = "lecture_links"

    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    source_name = Column(String, nullable=False)
    target_name = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.9)
    evidence = Column(Text, nullable=True)

    lecture = relationship("Lecture", back_populates="lecture_links")


class GraphNode(Base):
    """Canonical concept node in a course's prerequisite graph (Phase 4).

    One row per deduplicated concept name, per course. Edges reference nodes
    by name (dedup makes names stable across lectures); re-running graph
    construction replaces a course's rows as a set, so Stage 7 refinement can
    update edges safely.
    """

    __tablename__ = "graph_nodes"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class GraphEdge(Base):
    """Prerequisite edge A -> B (A must precede B) with classifier confidence.

    `source_method` records where the edge came from: "transcript" (voiced in
    a lecture, LectureLink, confidence 0.9 — the primary signal) or
    "classifier" (the LectureBank-trained fallback). `evidence` is the
    verbatim quote for transcript edges — the "why" the dashboard renders.
    """

    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)
    target = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    source_method = Column(
        String,
        nullable=False,
        default="classifier",
        server_default="classifier",
    )
    evidence = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class Clip(Base):
    """An ffmpeg-cut clip for one concept of one lecture (Phase 5).

    Points at the video file under data/processed/clips/<lecture_id>/; the
    concept it demonstrates and its timestamp range are kept so the
    remediation loop (Stage 6/7) can play clips back in prerequisite order.
    Re-running clip generation replaces a lecture's rows as a set.
    """

    __tablename__ = "clips"

    id = Column(Integer, primary_key=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id"), nullable=False, index=True)
    concept_id = Column(Integer, ForeignKey("concepts.id"), nullable=True)
    concept_name = Column(String, nullable=False)
    start_s = Column(Float, nullable=False)
    end_s = Column(Float, nullable=False)
    path = Column(String, nullable=False)
    ok = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    lecture = relationship("Lecture", back_populates="clips")


class ConceptItem(Base):
    """A quiz question targeting one concept of one course (Phase 6).

    The question is a graded MCQ (Stage 6b/6c): `question` is the stem, the
    distractor columns are the wrong options, and `answer` is the ground-truth
    option text so the server grades the submission. `explanation` (+ matching
    rationale_* columns) is the post-submit feedback shown to students: why the
    answer is correct and why each distractor is wrong. `order` is the suggested
    concept order within the quiz (from the course's learner order).
    """

    __tablename__ = "quiz_questions"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    concept = Column(String, nullable=False)
    question = Column(Text, nullable=False)
    distractor_a = Column(String, nullable=True)
    distractor_b = Column(String, nullable=True)
    distractor_c = Column(String, nullable=True)
    answer = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    rationale_a = Column(String, nullable=True)
    rationale_b = Column(String, nullable=True)
    rationale_c = Column(String, nullable=True)
    order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class QuizResponse(Base):
    """One student's answer to one quiz question (Phase 6).

    `correct` is the ground-truth correctness of the answer; time-to-answer
    (`latency_s`) and the wrong option selected (`selected`) additionally
    feed the confusion heatmap (Phase 8).
    """

    __tablename__ = "quiz_responses"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    student_id = Column(String, nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("quiz_questions.id"), nullable=False)
    concept = Column(String, nullable=False)
    selected = Column(String, nullable=True)
    correct = Column(Integer, nullable=False)
    latency_s = Column(Float, nullable=True)
    attempt = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    question = relationship("ConceptItem")


def _migrate_schema() -> None:
    """Lightweight additive migrations for DBs created by older code.

    create_all() does not alter existing tables, so columns added to the
    models need an explicit ALTER TABLE on live databases. Idempotent.
    Runs AFTER create_all() in init_db so fresh databases (no tables yet)
    are created with the current model and every ALTER here becomes a no-op.
    `passages` / `lecture_links` are NEW tables, so create_all() covers them;
    only the extra COLUMNS on existing tables are touched here.
    """
    from sqlalchemy import inspect, text

    # (column, SQLAlchemy type, kwargs, SQLite DDL type, SQL DEFAULT literal)
    additions = {
        "quiz_questions": [
            ("answer", Text, dict(nullable=True), "TEXT", None),
            ("explanation", Text, dict(nullable=True), "TEXT", None),
            ("rationale_a", String, dict(nullable=True), "VARCHAR", None),
            ("rationale_b", String, dict(nullable=True), "VARCHAR", None),
            ("rationale_c", String, dict(nullable=True), "VARCHAR", None),
        ],
        "concepts": [
            ("passage_id", Integer, dict(nullable=True), "INTEGER", None),
        ],
        "graph_edges": [
            ("source_method", String,
             dict(nullable=False, default="classifier", server_default="classifier"),
             "VARCHAR", "'classifier'"),
            ("evidence", Text, dict(nullable=True), "TEXT", None),
        ],
    }

    try:
        insp = inspect(engine)
        table_cols = {
            table: {c["name"] for c in insp.get_columns(table)}
            for table in additions
            if insp.has_table(table)
        }
    except Exception:
        table_cols = {}

    with engine.begin() as conn:
        for table, cols in additions.items():
            existing = table_cols.get(table) or set()
            for name, coltype, kwargs, ddl_type, ddl_default in cols:
                if existing and name in existing:
                    continue
                ddl = f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"
                if ddl_default is not None:
                    ddl += f" DEFAULT {ddl_default}"
                conn.execute(text(ddl))


def init_db() -> None:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_schema()
