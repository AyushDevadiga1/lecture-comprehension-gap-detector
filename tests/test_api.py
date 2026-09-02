"""
Route/API-level integration tests for the Flask FastAPI layer.

These cover the request->worker->persistence wiring that the pure-logic unit
suites deliberately skip: status-code guards, background workers, and DB rows
written/returned by the endpoints.

Hermetic strategy: the app's SessionLocal is monkeypatched to an in-memory
SQLite engine; heavy pipeline entry points (transcribe / LLM extraction /
clip cutting / classifier + graph embeddings) are monkeypatched, so no model
download, no real media, no LectureBank, and the real lecgap.db is untouched.

Note: FastAPI BackgroundTasks are executed synchronously by TestClient, so a
worker can also be invoked manually for determinism (workers are idempotent —
they replace a scope's rows).
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.api import routes as R  # noqa: E402 — same module object the fixture patches
from backend.models import db as models  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from fastapi.testclient import TestClient
    from backend.main import app

    # TestClient serves the app from a different thread; ":memory:" is
    # per-connection, so pin every connection to ONE shared :memory: db.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(R, "SessionLocal", Session)
    return TestClient(app), Session


class DummyGraph:
    """Stand-in for ConceptGraph: preserves wiring, skips embedding work."""

    def __init__(self, **kwargs):
        self._nodes = []
        self._edges = []
        self.removed_edges = []

    def add_concepts(self, names):
        for n in names:
            n = str(n).strip()
            if n and n not in self._nodes:
                self._nodes.append(n)
        return [str(n).strip() for n in names]

    def add_concepts_verbatim(self, names):
        return self.add_concepts(names)

    def add_edge(self, a, b, confidence):
        a, b = str(a).strip(), str(b).strip()
        if a and b and a != b and not any(
            e["source"] == a and e["target"] == b for e in self._edges
        ):
            self._edges.append({"source": a, "target": b, "confidence": float(confidence)})

    def resolve_cycles(self):
        return []

    def nodes(self):
        return list(self._nodes)

    def edges(self):
        return [dict(e) for e in self._edges]

    def topological_order(self):
        return self.nodes()

    def to_dict(self):
        return {
            "nodes": self.nodes(),
            "edges": self.edges(),
            "removed_edges": [],
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "is_dag": True,
            "topological_order": self.topological_order(),
        }


def _add_lecture(Session, *, course_id="ml1", status="ready", title="t",
                 source_path=None):
    with Session() as s:
        lec = models.Lecture(course_id=course_id, title=title, status=status,
                             source_path=source_path)
        s.add(lec)
        s.commit()
        return lec.id


# ------------------------------------------------------------------ lectures

def test_upload_lecture_rejects_bad_extension(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(R, "transcribe", lambda path: [])
    r = client.post(
        "/lectures",
        files={"file": ("notes.txt", b"abc", "text/plain")},
        data={"course_id": "ml1"},
    )
    assert r.status_code == 400


def test_upload_lecture_and_list(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(R, "transcribe", lambda path: [])

    r = client.post(
        "/lectures",
        files={"file": ("lec.mp4", b"fake", "video/mp4")},
        data={"course_id": "ml1", "title": "Intro"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["course_id"] == "ml1"
    assert body["title"] == "Intro"
    assert body["status"] == "uploaded"

    assert len(client.get("/lectures").json()) == 1

    with Session() as s:  # clean up the file + row the upload endpoint created
        lec = s.get(models.Lecture, body["id"])
        if lec and lec.source_path:
            Path(lec.source_path).unlink(missing_ok=True)
        s.query(models.Lecture).delete()
        s.commit()


# ------------------------------------------------------- concept extraction

def test_concept_extraction_requires_ready(api):
    client, Session = api
    lid = _add_lecture(Session, status="uploaded")
    assert client.post(f"/lectures/{lid}/concepts").status_code == 409
    assert client.post("/lectures/9999/concepts").status_code == 404


def test_concept_extraction_flow(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(R, "transcribe", lambda path: [])
    monkeypatch.setattr(
        R,
        "extract_spoken_concepts",
        lambda docs: [{"name": "Neural Network", "source": "spoken",
                       "implicit": False, "start_s": 0.0, "end_s": 5.0}],
    )
    lid = _add_lecture(Session, status="ready")

    assert client.post(f"/lectures/{lid}/concepts").status_code == 200
    R._extract_concepts_worker(lid)

    detail = client.get(f"/lectures/{lid}").json()
    assert [c["name"] for c in detail["concepts"]] == ["Neural Network"]
    assert [c["source"] for c in detail["concepts"]] == ["spoken"]


# --------------------------------------------------------------- course graph

def test_course_graph_build_and_fetch(api, monkeypatch):
    client, Session = api
    from backend.pipeline import classify_prerequisites as CP

    monkeypatch.setattr(R, "ConceptGraph", DummyGraph)
    monkeypatch.setattr(
        CP,
        "classify_course_pairs",
        lambda concepts: [{"a": "Gradient Descent", "b": "Loss Function",
                           "confidence": 0.8}],
    )
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add_all([
            models.Concept(course_id="ml1", lecture_id=lid,
                           name="Gradient Descent", source="spoken"),
            models.Concept(course_id="ml1", lecture_id=lid,
                           name="Loss Function", source="spoken"),
        ])
        s.commit()

    assert client.post("/courses/ml1/graph").status_code == 202
    R._build_course_graph_worker("ml1")

    g = client.get("/courses/ml1/graph").json()
    assert set(g["nodes"]) == {"Gradient Descent", "Loss Function"}
    assert g["edges"] == [{"source": "Gradient Descent", "target": "Loss Function",
                           "confidence": 0.8}]
    assert g["is_dag"] is True


def test_course_graph_404_without_rows(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(R, "ConceptGraph", DummyGraph)
    assert client.get("/courses/ml1/graph").status_code == 404


# --------------------------------------------------------------------- clips

def test_clips_guards(api):
    client, Session = api
    assert client.post("/lectures/9999/clips").status_code == 404
    assert client.get("/lectures/9999/clips").status_code == 404

    uploaded = _add_lecture(Session, status="uploaded")
    assert client.post(f"/lectures/{uploaded}/clips").status_code == 409

    ready_no_concepts = _add_lecture(Session, status="ready")
    assert client.post(f"/lectures/{ready_no_concepts}/clips").status_code == 409


def test_clips_cut_and_list(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(
        R,
        "cut_concept_clips",
        lambda media, concepts, out_dir: [
            {
                "name": c["name"],
                "start_s": c["start_s"],
                "end_s": c["end_s"],
                "path": (str(REPO / "data" / "processed" / "clips" / "0.mp4")
                         if c["name"] == "Ok" else None),
                "ok": c["name"] == "Ok",
                "error": None if c["name"] == "Ok" else "ffmpeg failed",
            }
            for c in concepts
        ],
    )
    lid = _add_lecture(Session, status="ready", source_path="media.mp4")
    with Session() as s:
        s.add_all([
            models.Concept(course_id="ml1", lecture_id=lid, name="Ok",
                           source="spoken", start_s=0.0, end_s=1.0),
            models.Concept(course_id="ml1", lecture_id=lid, name="Bad",
                           source="spoken", start_s=1.0, end_s=2.0),
        ])
        s.commit()

    assert client.post(f"/lectures/{lid}/clips").status_code == 202
    R._cut_clips_worker(lid)

    batch = client.get(f"/lectures/{lid}/clips").json()
    assert batch["status"] == "ready"
    by_name = {c["concept_name"]: c for c in batch["clips"]}
    assert by_name["Ok"]["ok"] is True
    assert by_name["Bad"]["ok"] is False
    assert by_name["Bad"]["error"] == "ffmpeg failed"


# ------------------------------------------------------------- quiz (Stage 6)

def test_create_quiz_and_submit_returns_remediation(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(R, "ConceptGraph", DummyGraph)
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="B",
                             source="spoken", start_s=1.0, end_s=2.0))
        s.add(models.GraphNode(course_id="ml1", name="A"))
        s.add(models.GraphNode(course_id="ml1", name="B"))
        s.add(models.GraphEdge(course_id="ml1", source="A", target="B",
                               confidence=0.9))
        s.commit()

    quiz = client.post("/quizzes", json={"course_id": "ml1", "student_id": "s1"})
    assert quiz.status_code == 201
    qs = quiz.json()["questions"]
    ids = {q["concept"]: q["id"] for q in qs}
    assert set(ids) == {"A", "B"}

    # student fails B -> remediation should list A (upstream) then B
    submit = client.post(
        "/quizzes/submit",
        json={
            "course_id": "ml1", "student_id": "s1",
            "answers": [
                {"question_id": ids["A"], "selected": "correct", "correct": True},
                {"question_id": ids["B"], "selected": "incorrect", "correct": False},
            ],
        },
    )
    assert submit.status_code == 200
    body = submit.json()
    assert body["score"] == 1 and body["total"] == 2
    rem = [(x["concept"], x["failed"]) for x in body["remediation"]]
    assert rem == [("A", False), ("B", True)]


def test_quiz_submit_unknown_question_404(api):
    client, _ = api
    r = client.post(
        "/quizzes/submit",
        json={"course_id": "ml1", "student_id": "s1",
              "answers": [{"question_id": 999, "correct": True}]},
    )
    assert r.status_code == 404


# --------------------------------------------------------- faculty stats (8)

def test_course_stats_heatmap_and_divergence(api):
    client, Session = api
    # a ready lecture with concepts in a specific taught order
    with Session() as s:
        lec = models.Lecture(course_id="ml1", title="t", status="ready")
        s.add(lec)
        s.commit()
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="B",
                             source="spoken", start_s=1.0, end_s=2.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="B",
                             source="spoken", start_s=5.0, end_s=6.0))
        s.add(models.GraphNode(course_id="ml1", name="A"))
        s.add(models.GraphNode(course_id="ml1", name="B"))
        s.add(models.GraphEdge(course_id="ml1", source="B", target="A",
                               confidence=0.6))  # learned order B before A
        s.commit()
        lid = lec.id

    with Session() as s:
        qa = models.ConceptItem(course_id="ml1", concept="A",
                                question="qA", order=0)
        qb = models.ConceptItem(course_id="ml1", concept="B",
                                question="qB", order=1)
        s.add_all([qa, qb])
        s.commit()
        s.add(models.QuizResponse(course_id="ml1", student_id="p1",
                                  question_id=qa.id, concept="A",
                                  correct=0, latency_s=3.0))
        s.add(models.QuizResponse(course_id="ml1", student_id="p2",
                                  question_id=qa.id, concept="A",
                                  correct=1, latency_s=1.0))
        s.add(models.QuizResponse(course_id="ml1", student_id="p1",
                                  question_id=qb.id, concept="B",
                                  correct=1, latency_s=2.0))
        s.commit()

    stats = client.get("/courses/ml1/stats").json()
    heat = {h["concept"]: h for h in stats["heatmap"]}
    assert heat["A"]["rate"] == 0.5   # 1 of 2 wrong
    assert heat["B"]["rate"] == 0.0
    # taught order: A first (start_s 0), then B; learned order: B before A
    assert stats["taught_order"] == ["A", "B"]
    assert stats["learned_order"] == ["B", "A"]