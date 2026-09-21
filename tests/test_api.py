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
    monkeypatch.setattr(workers, "_rebuild_course_graph", lambda course_id, lecture_id=None: None)
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
    monkeypatch.setattr(workers, "_rebuild_course_graph", lambda course_id, lecture_id=None: None)
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


def test_graph_route_and_worker_track_lecture_progress(api, monkeypatch):
    """A POST /courses/{id}/graph with a lecture_id query param ties the
    rebuild's progress updates to that lecture, so the Streamlit monitor has a
    row to watch; on success the job settles on a 'ready' progress payload.
    """
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

    # TestClient runs BackgroundTasks synchronously, so the 202 response is
    # only returned once the worker has finished.
    r = client.post(f"/courses/ml1/graph?lecture_id={lid}")
    assert r.status_code == 202

    prog = workers.get_lecture_progress(lid)
    assert prog["status"] == "ready"
    assert prog["progress_pct"] == 100
    assert prog["stage"] == "ready"  # in-memory entry pruned -> DB fallback

    g = client.get("/courses/ml1/graph").json()
    assert set(g["nodes"]) == {"Gradient Descent", "Loss Function"}


def test_graph_worker_without_lecture_leaves_progress_untouched(api, monkeypatch):
    """The lecture_id arg is opt-in: the plain worker (no lecture) must not
    publish any progress rows for any lecture."""
    client, Session = api
    from backend.pipeline import classify_prerequisites as CP

    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    monkeypatch.setattr(CP, "classify_course_pairs", lambda concepts, **kw: [])
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid,
                             name="SVD", source="spoken"))
        s.commit()

    calls = []

    def spy(*a, **kw):
        calls.append(a)

    monkeypatch.setattr(workers, "update_lecture_progress", spy)
    workers._build_course_graph_worker("ml1")

    assert calls == []  # lecture-less rebuild publishes no progress at all
    g = client.get("/courses/ml1/graph").json()
    assert g["node_count"] == 1  # ...but the graph itself still built


def test_graph_worker_shortcircuit_settles_on_ready(api, monkeypatch):
    """When a course has no concepts the rebuild short-circuits, but the
    'ready' terminal state must still reach the monitored lecture (the caller
    re-publishes it after the no-op, and the DB fallback agrees)."""
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    lid = _add_lecture(Session, course_id="ml1", status="ready")

    workers._build_course_graph_worker("ml1", lecture_id=lid)

    prog = workers.get_lecture_progress(lid)
    assert prog["status"] == "ready"
    assert client.get("/courses/ml1/graph").status_code == 404


def test_graph_worker_error_sets_lecture_error_and_progress(api, monkeypatch):
    """A failed rebuild tied to a lecture must mark the lecture status=error
    with the sanitized message and settle the progress store on an error
    payload (the UI monitor shows it without leaking internals)."""
    client, Session = api

    def boom(course_id, lecture_id=None):
        raise RuntimeError("secret traceback: /tmp/evil path")

    monkeypatch.setattr(workers, "_rebuild_course_graph", boom)
    lid = _add_lecture(Session, course_id="ml1", status="ready")

    workers._build_course_graph_worker("ml1", lecture_id=lid)

    prog = workers.get_lecture_progress(lid)
    assert prog["status"] == "error"
    assert "secret traceback" not in prog["detail"]

    with Session() as s:
        lec = s.get(models.Lecture, lid)
        assert lec.status == "error"
        assert "secret traceback" not in (lec.error or "")
        assert "server logs" in (lec.error or "")


def test_course_graph_404_without_rows(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    assert client.get("/courses/ml1/graph").status_code == 404


def test_rebuild_graph_shortcircuits_without_concepts(api, monkeypatch):
    """A rebuild over a course with no extracted concepts writes nothing and
    never pulls in the classifier/encoder."""
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    workers._rebuild_course_graph("ml1")  # no concepts -> early return
    with Session() as s:
        assert s.query(models.GraphNode).count() == 0
        assert s.query(models.GraphEdge).count() == 0
    assert client.get("/courses/ml1/graph").status_code == 404


def test_rebuild_graph_drops_phantom_link_endpoints(api, monkeypatch):
    """H2: a spoken LectureLink whose endpoint was never extracted (LLM
    hallucination / name variant / cross-lecture reference) must not create an
    orphan GraphNode — the edge is skipped, not auto-created."""
    client, Session = api
    from backend.pipeline import classify_prerequisites as CP

    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    monkeypatch.setattr(CP, "classify_course_pairs", lambda concepts, **kw: [])
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="Gradient Descent",
                             source="spoken", start_s=0.0, end_s=10.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="Loss Function",
                             source="spoken", start_s=5.0, end_s=15.0))
        # end-to-end edge is grounded, but the Ghost is never extracted
        s.add(models.LectureLink(lecture_id=lid, source_name="Loss Function",
                                 target_name="Gradient Descent",
                                 evidence="we descend the gradient of the loss"))
        s.add(models.LectureLink(lecture_id=lid, source_name="Backpropagation",
                                 target_name="Loss Function",
                                 evidence="backprop references the loss"))
        s.commit()

    workers._rebuild_course_graph("ml1")

    g = client.get("/courses/ml1/graph").json()
    assert set(g["nodes"]) == {"Gradient Descent", "Loss Function"}
    assert g["edges"] == [
        {"source": "Loss Function", "target": "Gradient Descent",
         "confidence": 0.9, "source_method": "transcript",
         "evidence": "we descend the gradient of the loss"}
    ]


def test_rebuild_graph_llm_veto_demotes_not_drops_edge(api, monkeypatch):
    """M1: with LECGAP_LLM_REASONING=1, an LLM 'not a prerequisite' verdict
    must demote the classifier edge's confidence (weighted), never delete it —
    the verdict is one fallible signal, not a binary gate."""
    client, Session = api
    from backend.pipeline import classify_prerequisites as CP

    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    monkeypatch.setenv("LECGAP_LLM_REASONING", "1")
    confirmed = [{"a": "Fourier Transform", "b": "Convolution", "confidence": 0.8}]
    monkeypatch.setattr(CP, "classify_course_pairs", lambda concepts, **kw: confirmed)

    def llm_veto(a, b, prediction=None, confidence=None):
        return {
            "prediction": False,
            "adjusted_confidence": confidence * 0.4,
            "reason": "no spoken link",
            "backend": "fake",
            "cached": True,
        }

    monkeypatch.setattr(CP, "llm_reasoning_check", llm_veto)
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="Fourier Transform",
                             source="spoken", start_s=0.0, end_s=10.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="Convolution",
                             source="spoken", start_s=5.0, end_s=15.0))
        s.commit()

    workers._rebuild_course_graph("ml1")

    g = client.get("/courses/ml1/graph").json()
    assert len(g["edges"]) == 1
    edge = g["edges"][0]
    assert edge["source"] == "Fourier Transform"
    assert edge["target"] == "Convolution"
    assert edge["confidence"] == pytest.approx(0.8 * 0.4)
    assert edge["source_method"] == "classifier+llm"
    assert edge["evidence"] == "no spoken link"


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
        lambda media, concepts, out_dir, on_done=None: [
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
    assert all(k not in first for k in ("answer", "explanation",
                                        "distractor_a", "distractor_b", "distractor_c"))

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


def test_create_quiz_batch_loads_passages(api, monkeypatch):
    """H6: passage rows are fetched with a single IN query, not one db.get per
    concept — provable by counting passage SELECTs during quiz creation."""
    from sqlalchemy import event

    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    lid = _add_lecture(Session, course_id="ml9", status="ready")
    engine = Session.kw["bind"]
    counts = {"passage_selects": 0}

    def _count(conn, cur, stmt, params, context, executemany):
        sql = str(stmt)
        if sql.lstrip().upper().startswith("SELECT") and "FROM passages" in sql:
            counts["passage_selects"] += 1

    event.listen(engine, "after_cursor_execute", _count)
    try:
        with Session() as s:
            for i in range(4):
                p = models.Passage(lecture_id=lid, idx=i, title=f"p{i}",
                                   kind="explain", start_s=float(i),
                                   end_s=float(i + 1), summary="s",
                                   text=f"the teaching passage for c{i}")
                s.add(p)
                s.flush()
                s.add(models.Concept(course_id="ml9", lecture_id=lid,
                                     passage_id=p.id, name=f"C{i}",
                                     source="spoken", start_s=float(i),
                                     end_s=float(i + 1)))
                s.add(models.TranscriptSegment(lecture_id=lid, idx=i,
                                               start_s=float(i) + 0.1,
                                               end_s=float(i) + 0.9,
                                               text=f"the c{i} concept is taught"))
            s.commit()

        r = client.post("/quizzes", json={"course_id": "ml9", "student_id": "s"})
        assert r.status_code == 201
        assert len(r.json()["questions"]) == 4
        # one batched passage fetch for all four concepts (was 4x db.get)
        assert counts["passage_selects"] == 1
    finally:
        event.remove(engine, "after_cursor_execute", _count)


def test_quiz_submit_unknown_question_404(api):
    client, _ = api
    r = client.post(
        "/quizzes/submit",
        json={"course_id": "ml1", "student_id": "s1",
              "answers": [{"question_id": 999, "correct": True}]},
    )
    assert r.status_code == 404


def test_quiz_submit_rejects_cross_course_question(api):
    """M3: a question may only be answered under its own course."""
    client, Session = api
    with Session() as s:
        s.add(models.ConceptItem(course_id="ml1", concept="A",
                                 question="qA", answer="optA", order=0))
        s.commit()
        qid = s.query(models.ConceptItem).first().id
    r = client.post(
        "/quizzes/submit",
        json={"course_id": "OTHER", "student_id": "p1",
              "answers": [{"question_id": qid, "selected": "optA"}]},
    )
    assert r.status_code == 400


def test_quiz_submit_ignores_client_correct_flag(api, monkeypatch):
    """M3: the client-supplied `correct` flag is dropped — a legacy question
    with no stored key grades as wrong even when the client claims success."""
    client, Session = api
    with Session() as s:
        q = models.ConceptItem(course_id="ml1", concept="A",
                               question="qA", order=0)  # answer is NULL
        s.add(q)
        s.commit()
        qid = q.id
    r = client.post(
        "/quizzes/submit",
        json={"course_id": "ml1", "student_id": "spoof",
              "answers": [{"question_id": qid, "correct": True}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["feedback"][0]["correct"] is False
    assert body["score"] == 0


def test_create_quiz_404_without_concepts(api):
    """A course with no extracted concepts cannot host a quiz."""
    client, _ = api
    r = client.post("/quizzes", json={"course_id": "empty", "student_id": "s"})
    assert r.status_code == 404


def test_quiz_submit_increments_attempt_per_student_question(api):
    client, Session = api
    with Session() as s:
        q = models.ConceptItem(course_id="ml1", concept="A",
                               question="qA", answer="optA", order=0)
        s.add(q)
        s.commit()
        qid = q.id
    body = {
        "course_id": "ml1", "student_id": "s1",
        "answers": [{"question_id": qid, "selected": "optA"}],
    }
    assert client.post("/quizzes/submit", json=body).status_code == 200
    assert client.post("/quizzes/submit", json=body).status_code == 200
    with Session() as s:
        rows = (s.query(models.QuizResponse)
                .filter_by(course_id="ml1", student_id="s1", question_id=qid)
                .order_by(models.QuizResponse.attempt)
                .all())
        assert [r.attempt for r in rows] == [1, 2]
        assert all(r.correct == 1 for r in rows)


def test_get_remediation_returns_latest_sequence(api, monkeypatch):
    client, Session = api
    monkeypatch.setattr(workers, "ConceptGraph", DummyGraph)
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="B",
                             source="spoken", start_s=1.0, end_s=2.0))
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.2,
                                       end_s=0.8, text="the A concept is alpha"))
        s.add(models.TranscriptSegment(lecture_id=lid, idx=1, start_s=1.2,
                                       end_s=1.8, text="the B concept is beta"))
        s.add(models.GraphNode(course_id="ml1", name="A"))
        s.add(models.GraphNode(course_id="ml1", name="B"))
        s.add(models.GraphEdge(course_id="ml1", source="A", target="B",
                               confidence=0.9))
        s.add(models.Clip(lecture_id=lid, concept_name="A", start_s=0.0,
                          end_s=1.0, path="clips/a.mp4", ok=1))
        s.commit()

    quiz = client.post("/quizzes", json={"course_id": "ml1", "student_id": "s1"})
    assert quiz.status_code == 201
    qs = quiz.json()["questions"]
    ids = {q["concept"]: q["id"] for q in qs}
    fail_opt = next(o for o in qs[1]["options"]
                    if o != "the B concept is beta")
    sub = client.post(
        "/quizzes/submit",
        json={"course_id": "ml1", "student_id": "s1",
              "answers": [
                  {"question_id": ids["A"], "selected": "the A concept is alpha"},
                  {"question_id": ids["B"], "selected": fail_opt},
              ]},
    )
    assert sub.status_code == 200

    rem = client.get("/students/s1/remediation", params={"course_id": "ml1"})
    assert rem.status_code == 200
    body = rem.json()
    assert body["total"] == 2 and body["score"] == 1
    watch = [(x["concept"], x["failed"]) for x in body["remediation"]]
    # upstream A (has a clip) then the failed B — prerequisite first
    assert watch == [("A", False), ("B", True)]
    # clips are attached for playback where they exist
    assert body["remediation"][0]["clip"] == "clips/a.mp4"
    # the remediation endpoint never discloses the answer key or per-question
    # feedback — that stays on the post-submit response only (SECURITY_AUDIT #22)
    assert body["feedback"] == []


def test_get_remediation_404_without_responses(api):
    client, _ = api
    r = client.get("/students/nobody/remediation", params={"course_id": "ml1"})
    assert r.status_code == 404


# ------------------------------------------- worker failure status + sanitization

def test_transcription_worker_error_is_sanitized_and_sets_status(api, monkeypatch):
    """H1 + M2: a failing pipeline stage must set Lecture.status='error' (not
    leave it 'ready') and persist a GENERIC error — never ffmpeg stderr/temp
    paths/Groq internals."""
    client, Session = api
    lid = _add_lecture(Session, status="uploaded")

    monkeypatch.setattr(
        workers, "transcribe",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("ffmpeg error: /tmp/xyz-273/audio.flac: invalid data")
        ),
    )
    workers._process_lecture(lid)

    detail = client.get(f"/lectures/{lid}").json()
    assert detail["status"] == "error"
    err = detail["error"]
    assert err
    for secret in ("ffmpeg", "/tmp", "RuntimeError", "invalid data"):
        assert secret not in err
    # the generic message still tells the operator WHERE it failed
    assert "Transcription" in err
    assert "logs" in err

    prog = client.get(f"/lectures/{lid}/progress").json()
    assert prog["status"] == "error"


def test_extraction_worker_total_failure_is_sanitized(api, monkeypatch):
    """H1: when the structure pass AND its chunk-atomic fallback both fail, the
    lecture lands in status=error with a generic message (no internal detail)."""
    client, Session = api
    lid = _add_lecture(Session, status="ready")

    def boom(docs):
        raise RuntimeError("groq 500: INTERNAL gsk_...")

    monkeypatch.setattr(workers, "extract_lecture_structure", boom)
    monkeypatch.setattr(workers, "extract_spoken_concepts", boom)
    workers._extract_concepts_worker(lid)

    detail = client.get(f"/lectures/{lid}").json()
    assert detail["status"] == "error"
    for secret in ("gsk_", "500", "RuntimeError"):
        assert secret not in detail["error"]


def test_clips_worker_error_is_sanitized_and_sets_status(api, monkeypatch):
    """H1 + M2: a clipping-stage exception marks the lecture error and does not
    surface ffmpeg stderr to the client."""
    client, Session = api
    lid = _add_lecture(Session, status="ready", source_path="media.mp4")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.commit()

    monkeypatch.setattr(
        workers, "cut_concept_clips",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("/tmp/lecgap-8x.mp4: Invalid NAL unit")
        ),
    )
    workers._cut_clips_worker(lid)

    detail = client.get(f"/lectures/{lid}").json()
    assert detail["status"] == "error"
    assert "/tmp" not in detail["error"]
    assert "Clip cutting" in detail["error"]


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


# --------------------------------------------------- progress / delete / rerun

def test_lecture_progress_live_and_db_fallback(api):
    client, Session = api
    lid = _add_lecture(Session, status="uploaded")

    # no live job -> DB-derived fallback snapshot
    r = client.get(f"/lectures/{lid}/progress")
    assert r.status_code == 200
    body = r.json()
    assert body["lecture_id"] == lid
    assert body["status"] == "uploaded"
    assert body["elapsed_s"] == 0.0
    assert isinstance(body["updated_at"], str)

    # a live job supersedes the DB fallback and keeps its own timing
    workers.update_lecture_progress(
        lid, "extracting", 42, "Running structure pass...", status="extracting"
    )
    body = client.get(f"/lectures/{lid}/progress").json()
    assert body["status"] == "extracting"
    assert body["stage"] == "extracting"
    assert body["progress_pct"] == 42
    assert body["detail"] == "Running structure pass..."
    assert body["elapsed_s"] >= 0.0

    workers._progress_finish(lid)
    body = client.get(f"/lectures/{lid}/progress").json()
    assert body["status"] == "uploaded"

    assert client.get("/lectures/9999/progress").status_code == 200
    assert client.get("/lectures/9999/progress").json()["status"] == "not_found"


def test_delete_lecture_purges_course_only_when_orphaned(api):
    """F-2 regression: deleting the LAST lecture of a course must also clear
    the course-scoped leftovers (graph rows, quiz rows) that outlived it."""
    client, Session = api
    with Session() as s:  # two lectures, shared course with graph + quiz rows
        for _ in range(2):
            s.add(models.Lecture(course_id="ml1", title="t", status="ready",
                                 source_path="nonexistent-media.mp4"))
        s.commit()
    with Session() as s:
        for lec in s.query(models.Lecture).all():
            s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="A",
                                 source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.GraphNode(course_id="ml1", name="A"))
        qa = models.ConceptItem(course_id="ml1", concept="A", question="q", order=0)
        s.add(qa)
        s.commit()
        s.add(models.QuizResponse(course_id="ml1", student_id="p",
                                  question_id=qa.id, concept="A",
                                  correct=1, latency_s=1.0))
        s.commit()
        ids = [lec.id for lec in s.query(models.Lecture).all()]

    # one lecture remains -> course-scoped rows survive
    r = client.delete(f"/lectures/{ids[0]}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    with Session() as s:
        assert s.query(models.GraphNode).filter_by(course_id="ml1").count() == 1
        assert s.query(models.ConceptItem).count() == 1

    # last lecture deleted -> the course's graph + quiz rows are swept too
    r = client.delete(f"/lectures/{ids[1]}")
    assert r.status_code == 200
    assert "course data purged" in r.json()["message"]
    with Session() as s:
        assert s.query(models.Lecture).filter_by(course_id="ml1").count() == 0
        assert s.query(models.GraphNode).filter_by(course_id="ml1").count() == 0
        assert s.query(models.ConceptItem).count() == 0
        assert s.query(models.QuizResponse).count() == 0

    assert client.delete("/lectures/9999").status_code == 404


def test_rerun_lecture(api, monkeypatch, tmp_path):
    client, Session = api
    monkeypatch.setattr(workers, "transcribe", lambda path, **kwargs: [])
    media = tmp_path / "lec.mp4"
    media.write_bytes(b"fake")
    lid = _add_lecture(Session, status="ready", source_path=str(media))

    r = client.post(f"/lectures/{lid}/rerun?whisper_backend=local")
    assert r.status_code == 200
    assert r.json()["status"] == "uploaded"  # reset before the bg job re-runs

    # missing media on disk -> HTTP 400 instead of a swallowed backtrace
    lost = _add_lecture(Session, status="ready", source_path="gone.mp4")
    assert client.post(f"/lectures/{lost}/rerun").status_code == 400


def test_upload_lecture_rejects_bad_whisper_backend(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(workers, "transcribe", lambda path, **kwargs: [])
    r = client.post(
        "/lectures",
        files={"file": ("lec.mp4", b"fake", "video/mp4")},
        data={"course_id": "ml1", "whisper_backend": "bogus"},
    )
    assert r.status_code == 400
    assert client.get("/lectures").json() == []  # nothing was persisted


# ------------------------------------------------------------ course manager

def test_course_list_summaries(api):
    client, Session = api
    with Session() as s:
        s.add_all([
            models.Lecture(course_id="ml1", title="a", status="ready"),
            models.Lecture(course_id="ml1", title="b", status="uploaded"),
            models.Lecture(course_id="ml2", title="c", status="ready"),
        ])
        s.add(models.Concept(course_id="ml1", lecture_id=1, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.GraphNode(course_id="ml1", name="A"))
        s.add(models.GraphEdge(course_id="ml1", source="A", target="B",
                               confidence=0.8))
        s.commit()

    courses_list = client.get("/courses").json()
    by_id = {c["course_id"]: c for c in courses_list}
    assert set(by_id) == {"ml1", "ml2"}
    assert by_id["ml1"]["total_lectures"] == 2
    assert by_id["ml1"]["ready_lectures"] == 1
    assert by_id["ml1"]["total_concepts"] == 1
    assert by_id["ml1"]["has_graph"] is True
    assert by_id["ml1"]["node_count"] == 1
    assert by_id["ml1"]["edge_count"] == 1
    assert by_id["ml2"]["has_graph"] is False


def test_delete_course_purges_everything(api, monkeypatch, tmp_path):
    client, Session = api
    media = tmp_path / "lec.mp4"
    media.write_bytes(b"fake")
    with Session() as s:
        s.add(models.Lecture(course_id="ml1", title="a", status="ready",
                             source_path=str(media)))
        s.commit()
        lid = s.query(models.Lecture).one().id
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.0,
                                       end_s=1.0, text="intro"))
        s.add(models.Passage(lecture_id=lid, idx=0, title="main", kind="explain",
                             start_s=0.0, end_s=1.0, text="passage text"))
        s.add(models.LectureLink(lecture_id=lid, source_name="B", target_name="A",
                                 confidence=0.9, evidence="we use B to get A"))
        s.add(models.Clip(lecture_id=lid, concept_name="A", start_s=0.0,
                          end_s=1.0, path=str(tmp_path / "clip.mp4"), ok=1))
        s.add(models.GraphNode(course_id="ml1", name="A"))
        s.add(models.GraphEdge(course_id="ml1", source="B", target="A",
                               confidence=0.9))
        qa = models.ConceptItem(course_id="ml1", concept="A", question="q", order=0)
        s.add(qa)
        s.commit()
        s.add(models.QuizResponse(course_id="ml1", student_id="p",
                                  question_id=qa.id, concept="A",
                                  correct=1, latency_s=1.0))
        s.commit()

    r = client.delete("/courses/ml1")
    assert r.status_code == 200
    assert r.json()["lectures_removed"] == 1
    assert not media.exists()  # raw media removed from disk

    with Session() as s:
        assert s.query(models.Lecture).count() == 0
        assert s.query(models.Concept).count() == 0
        assert s.query(models.TranscriptSegment).count() == 0
        assert s.query(models.Passage).count() == 0
        assert s.query(models.LectureLink).count() == 0
        assert s.query(models.Clip).count() == 0
        assert s.query(models.GraphNode).count() == 0
        assert s.query(models.GraphEdge).count() == 0
        assert s.query(models.ConceptItem).count() == 0
        assert s.query(models.QuizResponse).count() == 0

    assert client.delete("/courses/ml1").status_code == 404
    assert client.delete("/courses/nope").status_code == 404


def test_course_stats_falls_back_to_taught_order_without_graph(api):
    """The stats view must not 500 when a course has quiz responses but no
    built graph — learned_order falls back to taught_order (M5/P12 fallback
    branch)."""
    client, Session = api
    with Session() as s:
        lec = models.Lecture(course_id="ml1", title="t", status="ready")
        s.add(lec)
        s.commit()
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="B",
                             source="spoken", start_s=1.0, end_s=2.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        qa = models.ConceptItem(course_id="ml1", concept="A", question="qA", order=0)
        s.add(qa)
        s.commit()
        s.add(models.QuizResponse(course_id="ml1", student_id="p",
                                  question_id=qa.id, concept="A",
                                  correct=1, latency_s=1.0))
        s.commit()

    stats = client.get("/courses/ml1/stats").json()
    assert stats["taught_order"] == ["A", "B"]  # earliest mention first
    assert stats["learned_order"] == ["A", "B"]  # no graph -> taught fallback
    # identical orders -> every concept has a zero gap (no divergence)
    assert all(d["gap"] == 0 for d in stats["divergence"])


def test_course_stats_aggregates_in_sql(api):
    """M5: the heatmap comes from a GROUP BY aggregate, not a full-table
    hydration — pin correctness across many responses."""
    from backend.api.routes import courses as courses_mod

    client, Session = api
    with Session() as s:
        lec = models.Lecture(course_id="ml1", title="t", status="ready")
        s.add(lec)
        s.commit()
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.Concept(course_id="ml1", lecture_id=lec.id, name="B",
                             source="spoken", start_s=1.0, end_s=2.0))
        qa = models.ConceptItem(course_id="ml1", concept="A", question="qA", order=0)
        qb = models.ConceptItem(course_id="ml1", concept="B", question="qB", order=1)
        s.add_all([qa, qb])
        s.commit()
        for _ in range(20):  # 20 attempts on A, 5 wrong
            s.add(models.QuizResponse(course_id="ml1", student_id="p",
                                      question_id=qa.id, concept="A",
                                      correct=1, latency_s=1.0))
        for _ in range(5):
            s.add(models.QuizResponse(course_id="ml1", student_id="q",
                                      question_id=qa.id, concept="A",
                                      correct=0, latency_s=1.0))
        s.add(models.QuizResponse(course_id="ml1", student_id="r",
                                  question_id=qb.id, concept="B",
                                  correct=1, latency_s=1.0))
        s.commit()

    heat = {h["concept"]: h for h in client.get("/courses/ml1/stats").json()["heatmap"]}
    assert heat["A"] == {"concept": "A", "wrong": 5, "attempts": 25, "rate": 0.2}
    assert heat["B"]["wrong"] == 0 and heat["B"]["attempts"] == 1
    # the aggregate path must not hydrate QuizResponse rows: every statement
    # touching quiz_responses is an aggregate (contains GROUP BY), never a
    # bare SELECT of the full table.
    from sqlalchemy import event

    full_table_selects = []

    def _catch(conn, cur, stmt, params, context, executemany):
        sql = str(stmt)
        if "quiz_responses" in sql and sql.upper().startswith("SELECT") \
                and "GROUP BY" not in sql.upper():
            full_table_selects.append(sql)

    engine = Session.kw["bind"]
    event.listen(engine, "after_cursor_execute", _catch)
    try:
        client.get("/courses/ml1/stats")
    finally:
        event.remove(engine, "after_cursor_execute", _catch)
    assert full_table_selects == []


def test_course_graph_cache_self_heals_on_row_writes(api, monkeypatch):
    """M5: the graph-dict memo is served while the persisted graph is
    unchanged and rebuilds the moment a row write changes the signature."""
    from backend.pipeline.build_graph import ConceptGraph as RealConceptGraph
    from backend.api.routes import courses as courses_mod

    client, Session = api
    builds = []

    class Counting(RealConceptGraph):
        def __init__(self, *a, **kw):
            builds.append(1)
            super().__init__(*a, **kw)

    monkeypatch.setattr(courses_mod, "ConceptGraph", Counting)
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.GraphNode(course_id="ml1", name="A"))
        s.add(models.GraphNode(course_id="ml1", name="B"))
        s.add(models.GraphEdge(course_id="ml1", source="A", target="B",
                               confidence=0.9))
        s.commit()

    r1 = client.get("/courses/ml1/graph").json()
    r2 = client.get("/courses/ml1/graph").json()
    assert r1["node_count"] == 2 and r1["edge_count"] == 1
    assert r2 == r1
    assert len(builds) == 1  # memoized: second poll skips the graph build

    with Session() as s:
        s.add(models.GraphNode(course_id="ml1", name="C"))
        s.commit()

    r3 = client.get("/courses/ml1/graph").json()
    assert r3["node_count"] == 3
    assert len(builds) == 2  # signature changed -> rebuilt, not stale


def test_list_lectures_respects_limit_offset(api):
    """M5: GET /lectures is paginated (limit/offset) with backward-compatible
    defaults."""
    client, Session = api
    for _ in range(5):
        _add_lecture(Session, course_id="ml1", status="ready")

    all_rows = client.get("/lectures").json()
    assert len(all_rows) == 5
    page = client.get("/lectures", params={"limit": 2, "offset": 1}).json()
    assert [l["id"] for l in page] == [l["id"] for l in all_rows][1:3]
    assert client.get("/lectures", params={"limit": 0}).status_code == 400
    assert client.get("/lectures", params={"offset": -1}).status_code == 400


# ------------------------------------------------------- input bounds (schemas)

def test_quiz_input_bounds_are_enforced(api):
    """Schema/query bounds reject oversized and out-of-range input
    (SECURITY_AUDIT #23)."""
    client, Session = api
    lid = _add_lecture(Session, course_id="ml1", status="ready")
    with Session() as s:
        s.add(models.Concept(course_id="ml1", lecture_id=lid, name="A",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.2,
                                       end_s=0.8, text="the A concept is alpha"))
        s.commit()
    quiz = client.post("/quizzes", json={"course_id": "ml1", "student_id": "s1"})
    assert quiz.status_code == 201
    qid = quiz.json()["questions"][0]["id"]

    # oversized selected option
    r = client.post("/quizzes/submit", json={
        "course_id": "ml1", "student_id": "s1",
        "answers": [{"question_id": qid, "selected": "x" * 1001}]})
    assert r.status_code == 422

    # negative / absurd latency
    for bad in (-1.0, 90000.0):
        r = client.post("/quizzes/submit", json={
            "course_id": "ml1", "student_id": "s1",
            "answers": [{"question_id": qid, "selected": "opt", "latency_s": bad}]})
        assert r.status_code == 422

    # invalid course/student id patterns
    assert client.post("/quizzes", json={
        "course_id": "../etc", "student_id": "s1"}).status_code == 422
    assert client.post("/quizzes", json={
        "course_id": "ml1", "student_id": "a b"}).status_code == 422
    assert client.get("/students/s1/remediation",
                      params={"course_id": "../etc"}).status_code == 422


def test_question_out_shuffles_options_per_call():
    """SECURITY_AUDIT #7: options are no longer seeded by question id/concept,
    so the answer position varies across presentations."""
    from backend.api.workers import _question_out

    item = models.ConceptItem(
        course_id="ml1", concept="A", question="q", answer="right",
        distractor_a="w1", distractor_b="w2", distractor_c="w3", order=0,
    )
    item.id = 1
    positions = set()
    for _ in range(80):
        out = _question_out(item)
        assert set(out.options) == {"right", "w1", "w2", "w3"}
        positions.add(out.options.index("right"))
    assert len(positions) > 1