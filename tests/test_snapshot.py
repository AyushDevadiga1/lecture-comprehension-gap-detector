"""Tests for GET /courses/{id}/snapshot — derived readiness + in_flight.

Hermetic: temp SQLite DB; rows seeded directly through the ORM; no real jobs.
"""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ["LECGAP_DATABASE_URL"] = "sqlite:///data/test_snapshot_lecgap.db"

from backend.api.jobs.progress import update_lecture_progress  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models.db import (  # noqa: E402
    Clip,
    Concept,
    ConceptItem,
    GraphEdge,
    GraphNode,
    Lecture,
    QuizResponse,
    SessionLocal,
)
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _seed():
    # wipe any previous 'ml' fixture rows (same sqlite file across tests)
    with SessionLocal() as db:
        db.query(QuizResponse).filter(QuizResponse.course_id == "ml").delete(
            synchronize_session=False)
        db.query(ConceptItem).filter(ConceptItem.course_id == "ml").delete(
            synchronize_session=False)
        ml = [r[0] for r in db.query(Lecture.id).filter(Lecture.course_id == "ml")]
        db.query(Clip).filter(Clip.lecture_id.in_(ml)).delete(synchronize_session=False)
        db.query(Concept).filter(Concept.course_id == "ml").delete(synchronize_session=False)
        db.query(GraphEdge).filter(GraphEdge.course_id == "ml").delete(synchronize_session=False)
        db.query(GraphNode).filter(GraphNode.course_id == "ml").delete(synchronize_session=False)
        db.query(Lecture).filter(Lecture.course_id == "ml").delete(synchronize_session=False)
        db.commit()
    with SessionLocal() as db:
        db.add_all([
            Lecture(id=5001, course_id="ml", title="ready", status="ready"),
            Lecture(id=5002, course_id="ml", title="live", status="transcribing"),
            Lecture(id=5003, course_id="ml", title="waiting", status="uploaded"),
            Lecture(id=5004, course_id="ml", title="broken", status="error"),
        ])
        concepts = [
            Concept(course_id="ml", lecture_id=5001, name="Alpha"),
            Concept(course_id="ml", lecture_id=5001, name="Beta"),
        ]
        db.add_all(concepts)
        db.flush()  # materialize concept ids (FK target for clips)
        db.add_all([
            GraphNode(course_id="ml", name="Alpha"),
            GraphNode(course_id="ml", name="Beta"),
        ])
        db.add_all([
            GraphEdge(course_id="ml", source="Alpha", target="Beta",
                      confidence=0.9),
        ])
        db.add_all([
            Clip(lecture_id=5001, concept_id=concepts[0].id, concept_name="Alpha",
                 start_s=0.0, end_s=1.0, path="ok.mp4", ok=1),
            Clip(lecture_id=5001, concept_id=concepts[1].id, concept_name="Beta",
                 start_s=0.0, end_s=1.0, path="bad.mp4", ok=0),
        ])
        qs = [
            ConceptItem(course_id="ml", concept="Alpha", question="q1"),
            ConceptItem(course_id="ml", concept="Beta", question="q2"),
            ConceptItem(course_id="ml", concept="Beta", question="q3"),
        ]
        db.add_all(qs)
        db.flush()  # materialize question ids (FK target for responses)
        db.add_all([
            QuizResponse(course_id="ml", student_id="s1", question_id=qs[0].id,
                         concept="Alpha", selected="x", correct=0, latency_s=1.0),
            QuizResponse(course_id="ml", student_id="s2", question_id=qs[0].id,
                         concept="Alpha", selected="x", correct=0, latency_s=1.0),
        ])
        db.commit()
    update_lecture_progress(5002, "probing", 5, "probing...", status="transcribing")
    yield
    update_lecture_progress(5002, "ready", 100, "done", status="ready")


@pytest.fixture
def client():
    return TestClient(app)


def test_snapshot_derives_counts_and_in_flight(client):
    r = client.get("/courses/ml/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["lectures"] == {"total": 4, "ready": 1, "uploaded": 1,
                                "transcribing": 1, "error": 1}
    assert body["concepts"] == 2
    assert body["graph"] == {"has": True, "nodes": 2, "edges": 1}
    assert body["clips"] == {"cut": 2, "ok": 1}
    assert body["quiz"] == {"questions": 3, "respondents": 2}

    by_id = {f["lecture_id"]: f for f in body["in_flight"]}
    assert set(by_id) == {5002, 5003}  # transcribing + uploaded only
    assert by_id[5002]["status"] == "transcribing"
    assert by_id[5002]["stage"] == "probing"
    assert by_id[5002]["progress_pct"] == 5
    assert by_id[5003]["status"] == "uploaded"


def test_snapshot_unknown_course_is_empty_not_404(client):
    r = client.get("/courses/nosuch/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["lectures"] == {"total": 0, "ready": 0, "uploaded": 0,
                                "transcribing": 0, "error": 0}
    assert body["concepts"] == 0
    assert body["graph"] == {"has": False, "nodes": 0, "edges": 0}
    assert body["in_flight"] == []


def test_snapshot_rejects_bad_course_id(client):
    for bad in ("has space", "x" * 200):
        assert client.get(f"/courses/{bad}/snapshot").status_code == 422