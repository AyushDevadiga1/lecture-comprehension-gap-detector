"""
SQLite persistence layer — sits behind the API, never touched directly by
the frontend (see plan/ARCHITECTURE.md, "Decoupled architecture").

Tables are added incrementally as each phase actually needs to persist
something — not speculatively:

    Phase 1:  lectures, transcript_segments
    Phase 2:  llm_cache (prompt-hash keyed; quota protection), concepts
    Phase 4:  graph_nodes, graph_edges (per-course prerequisite graph)
    Later:    clips, quiz_questions, quiz_responses, students, refinement_log

Lecture.status lifecycle: uploaded -> transcribing -> ready | error
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
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

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    name = Column(String, nullable=False)
    source = Column(String, nullable=False, default="spoken")
    implicit = Column(Integer, nullable=False, default=0)
    start_s = Column(Float, nullable=True)
    end_s = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    lecture = relationship("Lecture", back_populates="concepts")


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
    """Prerequisite edge A -> B (A must precede B) with classifier confidence."""

    __tablename__ = "graph_edges"

    id = Column(Integer, primary_key=True)
    course_id = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False)
    target = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


def init_db() -> None:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
