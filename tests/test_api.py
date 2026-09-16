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

from backend.api import workers  # noqa: E402 — background worker symbols moved here
from backend.api.routes import courses, lectures, quizzes  # noqa: E402
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
    # each domain router + the workers share one SessionLocal source — patch
    # them all so endpoints and background jobs hit the in-memory store.
    for mod in (lectures, courses, quizzes, workers):
        monkeypatch.setattr(mod, "SessionLocal", Session)
    # quiz creation must not hit the real cached LLM in this suite — the
    # Stage 6c LLM path is exercised by its own targeted test (which re-patches).
    monkeypatch.setattr(quizzes, "generate_mcq", lambda *a, **k: None)
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
        if a and b and a != b and not self.has_edge(a, b):
            self._edges.append({"source": a, "target": b, "confidence": float(confidence)})

    def _resolve(self, name):
        return str(name).strip()

    def to_networkx(self):
        return self

    def has_edge(self, a, b):
        return any(
            e["source"] == a and e["target"] == b for e in self._edges
        )

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
    monkeypatch.setattr(workers, "transcribe", lambda path: [])
    r = client.post(
        "/lectures",
        files={"file": ("notes.txt", b"abc", "text/plain")},
        data={"course_id": "ml1"},
    )
    assert r.status_code == 400


def test_upload_lecture_and_list(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(workers, "transcribe", lambda path: [])

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
    monkeypatch.setattr(workers, "transcribe", lambda path: [])
    monkeypatch.setattr(
        workers,
        "extract_lecture_structure",
        lambda docs: {
            "passages": [
                {"title": "Intro to NNs", "kind": "explain", "start_s": 0.0,
                 "end_s": 5.0, "summary": "s", "text": "welcome passage",
                 "concepts": []},
            ],
            "concepts": [
                {"name": "Neural Network", "implicit": False, "start_s": 0.0,
                 "end_s": 3.0, "passage_index": 0},
            ],
            "links": [],
        },
    )
    # keep this suite hermetic: the chained graph rebuild is exercised by
    # test_concept_extraction_chains_graph_build with the classifier patched
    monkeypatch.setattr(workers, "_rebuild_course_graph", lambda course_id: None)
    lid = _add_lecture(Session, status="ready")

    assert client.post(f"/lectures/{lid}/concepts").status_code == 200
    workers._extract_concepts_worker(lid)

    detail = client.get(f"/lectures/{lid}").json()
    assert [c["name"] for c in detail["concepts"]] == ["Neural Network"]
    assert [c["source"] for c in detail["concepts"]] == ["spoken"]
    # the structure pass persists the teaching passage and links the concept
    # to it via passage_id (quiz/clip grounding reads that passage text later)
    with Session() as s:
        passage = s.query(models.Passage).one()
        concept = s.query(models.Concept).one()
        assert passage.title == "Intro to NNs"
        assert passage.text == "welcome passage"
        assert concept.passage_id == passage.id


def test_concept_extraction_falls_back_on_pass_failure(api, monkeypatch):
    """Whole-pass LLM failure (backend down) degrades to the old chunk-atomic
    path so a user is never stranded (plan/LECTURE_STRUCTURE.md §8)."""
    client, Session = api
    monkeypatch.setattr(workers, "transcribe", lambda path: [])

    def boom(docs):
        raise RuntimeError("LLM backend down")

    monkeypatch.setattr(workers, "extract_lecture_structure", boom)
    monkeypatch.setattr(
        workers,
        "extract_spoken_concepts",
        lambda docs: [{"name": "Neural Network", "source": "spoken",
                       "implicit": False, "start_s": 0.0, "end_s": 5.0}],
    )
    monkeypatch.setattr(workers, "refine_concept_times", lambda c, docs: c)
    monkeypatch.setattr(workers, "_rebuild_course_graph", lambda course_id: None)
    lid = _add_lecture(Session, status="ready")

    workers._extract_concepts_worker(lid)

    detail = client.get(f"/lectures/{lid}").json()
    assert [c["name"] for c in detail["concepts"]] == ["Neural Network"]
    with Session() as s:
        assert s.query(models.Passage).count() == 0
        assert s.query(models.LectureLink).count() == 0


def test_concept_extraction_chains_graph_build(api, monkeypatch):
    """Extraction worker rebuilds the course graph once concepts are persisted.

    Regression test for the UI race: the frontend fires POST /concepts and
    POST /graph back-to-back, and a concurrent graph worker can query an empty
    Concept table and silently exit. Chaining the rebuild into the extraction
    worker guarantees the graph reflects the fresh concepts either way.
    Chained rebuild is also transcript-first: the spoken link is persisted as
    a lecture_links row and becomes a 0.9-confidence edge with evidence, and
    the classifier's (weaker) take on the SAME pair is skipped.
    """
    client, Session = api
    from backend.pipeline import classify_prerequisites as CP

    monkeypatch.setattr(workers, "transcribe", lambda path: [])
    monkeypatch.setattr(
        workers,
        "extract_lecture_structure",
        lambda docs: {
            "passages": [],
            "concepts": [
                {"name": "Gradient Descent", "implicit": False,
                 "start_s": 0.0, "end_s": 10.0, "passage_index": 0},
                {"name": "Loss Function", "implicit": False,
                 "start_s": 5.0, "end_s": 15.0, "passage_index": 0},
            ],
            "links": [
                {"from": "Loss Function", "to": "Gradient Descent",
                 "evidence": "to minimize the loss we take steps down its gradient"},
            ],
        },
    )
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    monkeypatch.setattr(
        CP,
        "classify_course_pairs",
        lambda concepts, **kw: [{"a": "Loss Function", "b": "Gradient Descent",
                           "confidence": 0.8}],  # already grounded -> skipped
    )
    lid = _add_lecture(Session, status="ready", course_id="ml1")

    workers._extract_concepts_worker(lid)

    g = client.get("/courses/ml1/graph").json()
    assert set(g["nodes"]) == {"Gradient Descent", "Loss Function"}
    assert g["edges"] == [
        {"source": "Loss Function", "target": "Gradient Descent",
         "confidence": 0.9, "source_method": "transcript",
         "evidence": "to minimize the loss we take steps down its gradient"}
    ]
    assert g["is_dag"] is True


# --------------------------------------------------------------- course graph

def test_course_graph_build_and_fetch(api, monkeypatch):
    client, Session = api
    from backend.pipeline import classify_prerequisites as CP

    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    monkeypatch.setattr(
        CP,
        "classify_course_pairs",
lambda concepts, **kw: [{"a": "Gradient Descent", "b": "Loss Function",
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
    workers._build_course_graph_worker("ml1")

    g = client.get("/courses/ml1/graph").json()
    assert set(g["nodes"]) == {"Gradient Descent", "Loss Function"}
    assert g["edges"] == [
        {"source": "Gradient Descent", "target": "Loss Function",
         "confidence": 0.8, "source_method": "classifier", "evidence": None}
    ]
    assert g["is_dag"] is True


def test_course_graph_404_without_rows(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
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
        workers,
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
    workers._cut_clips_worker(lid)

    batch = client.get(f"/lectures/{lid}/clips").json()
    assert batch["status"] == "ready"
    by_name = {c["concept_name"]: c for c in batch["clips"]}
    assert by_name["Ok"]["ok"] is True
    assert by_name["Bad"]["ok"] is False
    assert by_name["Bad"]["error"] == "ffmpeg failed"


# ------------------------------------------------------------- quiz (Stage 6)

def test_create_quiz_and_submit_returns_remediation(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="B",
                             source="spoken", start_s=1.0, end_s=2.0))
        # spoken evidence the MCQ machinery turns into graded options
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.2,
                                       end_s=0.8, text="the A concept is alpha"))
        s.add(models.TranscriptSegment(lecture_id=lid, idx=1, start_s=1.2,
                                       end_s=1.8, text="the B concept is beta"))
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
    # Stage 6b: questions are graded MCQs with real option sets
    by_name = {q["concept"]: q for q in qs}
    assert "the A concept is alpha" in by_name["A"]["options"]
    assert "the B concept is beta" in by_name["B"]["options"]

    # student fails B -> remediation should list A (upstream) then B
    fail_opt = next(o for o in by_name["B"]["options"]
                    if o != "the B concept is beta")
    submit = client.post(
        "/quizzes/submit",
        json={
            "course_id": "ml1", "student_id": "s1",
            "answers": [
                {"question_id": ids["A"], "selected": "the A concept is alpha"},
                {"question_id": ids["B"], "selected": fail_opt},
            ],
        },
    )
    assert submit.status_code == 200
    body = submit.json()
    assert body["score"] == 1 and body["total"] == 2
    rem = [(x["concept"], x["failed"]) for x in body["remediation"]]
    assert rem == [("A", False), ("B", True)]
    # per-question feedback is returned (evidence-based fallbacks carry no
    # explanation/rationale, but the correct/answer fields always populate)
    by_fb = {f["concept"]: f for f in body["feedback"]}
    assert by_fb["A"]["correct"] is True and by_fb["A"]["answer"] == "the A concept is alpha"
    assert by_fb["B"]["correct"] is False


def test_create_quiz_dedupes_shared_evidence(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    lid = _add_lecture(Session, course_id="ml2", status="ready")
    with Session() as s:
        for (name, st, en) in (("First", 0.0, 2.0), ("Second", 2.0, 4.0)):
            s.add(models.Concept(course_id="ml2", lecture_id=lid, name=name,
                                 source="spoken", start_s=st, end_s=en))
        # only one transcript sentence exists for BOTH concepts
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.0,
                                       end_s=4.0,
                                       text="the single shared concept sentence"))
        s.commit()

    qs = client.post("/quizzes",
                     json={"course_id": "ml2", "student_id": "s"}).json()["questions"]
    by_name = {q["concept"]: q for q in qs}
    shared = "the single shared concept sentence"
    # the shared sentence is used as an answer exactly once; the other concept
    # falls back to a distinct recognition question instead of duplicating it
    assert sum(shared in q["options"] for q in qs) == 1
    second = by_name["Second"]
    assert "Second" in second["options"]
    assert shared not in second["options"]


def test_create_quiz_uses_llm_mcq_when_available(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    monkeypatch.setattr(
        quizzes, "generate_mcq",
        lambda name, ctx: {
            "question": f"Which best describes '{name}' as taught?",
            "options": [f"{name} definition", "wrong one", "wrong two", "wrong three"],
            "answer": f"{name} definition",
            "explanation": f"the lecture defines {name} as its data model",
            "rationale": {"wrong one": "that is not definitional of it",
                          "wrong two": "that contradicts the lecture",
                          "wrong three": "that is a different concept"},
        },
    )
    lid = _add_lecture(Session, course_id="ml3", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml3", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.2,
                                       end_s=0.8, text="the A concept is alpha"))
        s.add(models.GraphNode(course_id="ml3", name="A"))
        s.commit()

    q = client.post("/quizzes",
                    json={"course_id": "ml3", "student_id": "s"}).json()
    first = q["questions"][0]
    # the server never leaks the answer key or the explanation via GET /quizzes
    assert first["question"] == "Which best describes 'A' as taught?"
    assert "A definition" in first["options"]
    assert len(first["options"]) == 4
    assert all(k not in first for k in ("answer", "explanation"))

    wrong_pick = next(o for o in first["options"] if o != "A definition")
    rationales = {"wrong one": "that is not definitional of it",
                  "wrong two": "that contradicts the lecture",
                  "wrong three": "that is a different concept"}
    sub = client.post(
        "/quizzes/submit",
        json={"course_id": "ml3", "student_id": "s",
              "answers": [{"question_id": first["id"], "selected": wrong_pick}]},
    ).json()
    fb = sub["feedback"][0]
    assert fb["correct"] is False
    assert fb["answer"] == "A definition"
    assert fb["explanation"] == "the lecture defines A as its data model"
    assert fb["rationale"] == rationales[wrong_pick]


def test_create_quiz_uses_passage_context(api, monkeypatch):
    """Stage 6 grounding: the MCQ writer reads the persisted teaching passage
    (extracted by the structure pass), not a re-scanned segment window."""
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    seen = {}
    monkeypatch.setattr(
        quizzes, "generate_mcq",
        lambda name, ctx: (seen.update(name=name, ctx=ctx), None)[1],
    )
    lid = _add_lecture(Session, course_id="ml4", status="ready")
    with Session() as s:
        p = models.Passage(lecture_id=lid, idx=0, title="Pivot Tables",
                           kind="explain", start_s=0.0, end_s=4.0,
                           summary="s",
                           text="the full teaching passage for pivot tables")
        s.add(p)
        s.flush()
        s.add(models.Concept(course_id="ml4", lecture_id=lid, passage_id=p.id,
                             name="Pivot Table", source="spoken",
                             start_s=1.0, end_s=3.0))
        # a transcript window that would be local_context's choice — the
        # passage text must win over it
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=1.0,
                                       end_s=2.0, text="VERBATIM SEGMENT"))
        s.commit()

    r = client.post("/quizzes", json={"course_id": "ml4", "student_id": "s"})
    assert r.status_code == 201
    assert seen.get("name") == "Pivot Table"
    assert seen.get("ctx") == "the full teaching passage for pivot tables"
    assert "VERBATIM" not in (seen.get("ctx") or "")


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