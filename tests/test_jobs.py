"""Hermetic unit tests for the background-job modules (backend/api/jobs/*)
and the shared query/graph helpers (backend/api/queries.py, graphs.py).

These pin the orchestration seams that used to be reachable only through the
full HTTP API: the progress store, the per-job error paths (sanitized messages,
lecture row flags, progress finalization), course teardown, and the cross-endpoint
read helpers. Pipeline leaf functions are faked; SessionLocal is replaced by an
in-memory SQLite so nothing touches the real DB or the network.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import graphs, queries
from backend.api.jobs import (
    clips as jobs_clips,
    extract as jobs_extract,
    graph as jobs_graph,
    progress as jobs_progress,
    purge as jobs_purge,
    transcribe as jobs_transcribe,
)
from backend.models import db as models


@pytest.fixture
def Session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    for mod in (jobs_progress, jobs_transcribe, jobs_extract, jobs_clips,
                jobs_graph, jobs_purge, queries, graphs):
        monkeypatch.setattr(mod, "SessionLocal", Session)
    return Session


def _lecture(Session, *, course_id="c1", status="ready", source_path=None):
    with Session() as s:
        lec = models.Lecture(course_id=course_id, title="t", status=status,
                             source_path=source_path)
        s.add(lec)
        s.commit()
        return lec.id


# ------------------------------------------------------------------ progress

def test_update_progress_clamps_and_finish_drops_to_db_fallback(Session):
    jobs_progress.update_lecture_progress(1, "extracting", 150, "done",
                                          status="extracting")
    snap = jobs_progress.get_lecture_progress(1)
    assert snap["status"] == "extracting"
    assert snap["progress_pct"] == 100  # clamped
    assert snap["detail"] == "done"
    assert snap["elapsed_s"] >= 0.0

    jobs_progress.update_lecture_progress(1, "extracting", -5, "neg")
    assert jobs_progress.get_lecture_progress(1)["progress_pct"] == 0

    jobs_progress._finish(1)
    # entry pruned -> DB-derived fallback (lecture 1 does not exist)
    assert jobs_progress.get_lecture_progress(1)["status"] == "not_found"


def test_get_progress_db_fallback_reads_lecture_status(Session):
    lid = _lecture(Session, status="uploaded")
    snap = jobs_progress.get_lecture_progress(lid)
    assert snap["status"] == "uploaded" and snap["progress_pct"] == 50


# ------------------------------------------------------- transcribe job (St 1)

def test_process_lecture_persists_segments_and_marks_ready(Session, monkeypatch):
    lid = _lecture(Session, status="uploaded", source_path="media.mp4")

    def fake_transcribe(path, **kwargs):
        assert path == "media.mp4"
        return [{"start": s, "end": s + 1.0, "text": f"seg{s}"} for s in (0.0, 2.0)]

    monkeypatch.setattr(jobs_transcribe, "transcribe", fake_transcribe)
    jobs_transcribe.process_lecture(lid)

    with Session() as s:
        lec = s.get(models.Lecture, lid)
        assert lec.status == "ready"
        assert [(seg.idx, seg.text, seg.start_s) for seg in lec.segments] == [
            (0, "seg0.0", 0.0), (1, "seg2.0", 2.0)]
    # progress store finalized -> db fallback says ready
    assert jobs_progress.get_lecture_progress(lid)["status"] == "ready"


def test_process_lecture_sanitizes_failure_and_flags_lecture(Session, monkeypatch):
    lid = _lecture(Session, status="uploaded")

    def boom(path, **kwargs):
        raise RuntimeError("ffmpeg stderr: /tmp/xyz/groq-key-ABCD leaked")

    monkeypatch.setattr(jobs_transcribe, "transcribe", boom)
    jobs_transcribe.process_lecture(lid)

    with Session() as s:
        lec = s.get(models.Lecture, lid)
        assert lec.status == "error"
        assert "ABCD" not in (lec.error or "")
        assert "groq" not in (lec.error or "").lower()
        assert "server logs" in (lec.error or "")


# ------------------------------------------------------- extract job (St 2)

def test_extract_worker_persists_passages_concepts_links(Session, monkeypatch):
    lid = _lecture(Session, status="ready")
    with Session() as s:
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.0,
                                       end_s=4.0, text="the NN passage"))
        s.commit()

    structure = {
        "passages": [{"title": "NNs", "kind": "explain", "start_s": 0.0,
                      "end_s": 4.0, "summary": "s", "text": "full passage text"}],
        "concepts": [{"name": "Neural Network", "implicit": False,
                      "start_s": 0.0, "end_s": 4.0, "passage_index": 0},
                     {"name": "Backprop", "implicit": True,
                      "start_s": 0.5, "end_s": 2.0}],
        "links": [{"from": "Neural Network", "to": "Backprop", "evidence": "e"}],
    }
    monkeypatch.setattr(jobs_extract, "extract_lecture_structure",
                        lambda docs: structure)
    monkeypatch.setattr(jobs_graph, "rebuild_course_graph",
                        lambda c, lecture_id=None: None)

    jobs_extract.extract_concepts_worker(lid)

    with Session() as s:
        passages = s.query(models.Passage).all()
        concepts = s.query(models.Concept).all()
        links = s.query(models.LectureLink).all()
        assert len(passages) == 1 and passages[0].text == "full passage text"
        by_name = {c.name: c for c in concepts}
        # the first concept carries its passage_id; the second falls back to None
        assert by_name["Neural Network"].passage_id == passages[0].id
        assert by_name["Backprop"].passage_id is None
        assert [(l.source_name, l.target_name) for l in links] == [
            ("Neural Network", "Backprop")]


def test_extract_worker_falls_back_when_structure_pass_fails(Session, monkeypatch):
    lid = _lecture(Session, status="ready")
    with Session() as s:
        s.add(models.TranscriptSegment(lecture_id=lid, idx=0, start_s=0.0,
                                       end_s=4.0, text="x"))
        s.commit()

    monkeypatch.setattr(jobs_extract, "extract_lecture_structure",
                        lambda docs: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(jobs_extract, "extract_spoken_concepts",
                        lambda docs: [{"name": "Rescue", "implicit": False,
                                       "start_s": 0.0, "end_s": 4.0}])
    monkeypatch.setattr(jobs_extract, "refine_concept_times",
                        lambda c, docs: c)
    monkeypatch.setattr(jobs_graph, "rebuild_course_graph",
                        lambda c, lecture_id=None: None)

    jobs_extract.extract_concepts_worker(lid)
    with Session() as s:
        assert [c.name for c in s.query(models.Concept).all()] == ["Rescue"]


# ------------------------------------------------------------ clips job (St 5)

def test_cut_clips_worker_persists_results(Session, monkeypatch):
    lid = _lecture(Session, status="ready", source_path="media.mp4")
    with Session() as s:
        s.add(models.Concept(lecture_id=lid, course_id="c1", name="Ok",
                             source="spoken", start_s=0.0, end_s=1.0))
        s.add(models.Concept(lecture_id=lid, course_id="c1", name="Bad",
                             source="spoken", start_s=1.0, end_s=2.0))
        s.commit()

    monkeypatch.setattr(
        jobs_clips, "cut_concept_clips",
        lambda media, concepts, out_dir, on_done=None: [
            {"path": "/out/0.mp4", "ok": c["name"] == "Ok",
             "error": None if c["name"] == "Ok" else "ffmpeg failed"}
            for c in concepts
        ],
    )
    jobs_clips.cut_clips_worker(lid)

    with Session() as s:
        clips = {c.concept_name: c for c in s.query(models.Clip).all()}
        assert clips["Ok"].ok == 1 and clips["Ok"].path == "/out/0.mp4"
        assert clips["Bad"].ok == 0 and clips["Bad"].error == "ffmpeg failed"


def test_cut_clips_worker_no_concepts_marks_ready(Session, monkeypatch):
    lid = _lecture(Session, status="ready")
    jobs_clips.cut_clips_worker(lid)
    assert jobs_progress.get_lecture_progress(lid)["status"] == "ready"


# ------------------------------------------------------------ graph job (St 4)

class FakeGraph:
    """Minimal ConceptGraph stand-in: nodes + edges, no embeddings."""

    def __init__(self, **kwargs):
        self._nodes = set()
        self._edges = []

    def add_concepts(self, names):
        for n in names:
            n = str(n).strip()
            if n:
                self._nodes.add(n)
        return list(names)

    def to_networkx(self):
        return self

    def _resolve(self, name):
        return str(name).strip()

    def has_edge(self, a, b):
        return any(e["source"] == a and e["target"] == b for e in self._edges)

    def add_edge(self, a, b, confidence):
        a, b = self._resolve(a), self._resolve(b)
        if a and b and a != b and not self.has_edge(a, b):
            self._edges.append({"source": a, "target": b,
                                "confidence": float(confidence)})

    def resolve_cycles(self):
        return []

    def nodes(self):
        return sorted(self._nodes)

    def edges(self):
        return [dict(e) for e in self._edges]


def test_rebuild_graph_transcript_first_and_phantom_drop(Session, monkeypatch):
    lid = _lecture(Session, status="ready")
    with Session() as s:
        for name, st, en in (("A", 0.0, 1.0), ("B", 1.0, 2.0)):
            s.add(models.Concept(lecture_id=lid, course_id="c1", name=name,
                                 source="spoken", start_s=st, end_s=en))
        s.add(models.LectureLink(lecture_id=lid, source_name="A",
                                 target_name="B", evidence="spoken"))
        # phantom: B -> Ghost, but "Ghost" was never extracted as a concept
        s.add(models.LectureLink(lecture_id=lid, source_name="B",
                                 target_name="Ghost", evidence="hallucinated"))
        s.commit()

    monkeypatch.setattr(jobs_graph, "ConceptGraph", FakeGraph)
    monkeypatch.setattr(jobs_graph, "get_shared_classifier",
                        lambda: type("Clf", (), {"_encoder": None,
                                                 "_get_encoder": lambda self: None})())
    from backend.pipeline import classify_prerequisites as CP
    monkeypatch.setattr(CP, "classify_course_pairs",
                        lambda concepts, **kw: (_ for _ in ()).throw(
                            ValueError("LectureBank absent")))

    jobs_graph.rebuild_course_graph("c1")

    with Session() as s:
        nodes = sorted(n.name for n in s.query(models.GraphNode).all())
        edges = s.query(models.GraphEdge).all()
        assert nodes == ["A", "B"]
        assert [(e.source, e.target, e.source_method) for e in edges] == [
            ("A", "B", "transcript")]
        assert "Ghost" not in nodes  # phantom endpoint dropped


def test_build_graph_worker_flags_lecture_on_failure(Session, monkeypatch):
    lid = _lecture(Session, status="uploaded")
    monkeypatch.setattr(jobs_graph, "rebuild_course_graph",
                        lambda c, lecture_id=None: (_ for _ in ()).throw(
                            RuntimeError("boom detail")))
    jobs_graph.build_course_graph_worker("c1", lecture_id=lid)

    with Session() as s:
        lec = s.get(models.Lecture, lid)
        assert lec.status == "error"
        assert "boom detail" not in (lec.error or "")


def test_build_graph_worker_without_lecture_touches_nothing(Session, monkeypatch):
    lid = _lecture(Session, status="uploaded")
    monkeypatch.setattr(jobs_graph, "rebuild_course_graph",
                        lambda c, lecture_id=None: (_ for _ in ()).throw(
                            RuntimeError("boom")))
    jobs_graph.build_course_graph_worker("c1")  # no lecture_id -> swallowed
    with Session() as s:
        assert s.get(models.Lecture, lid).status == "uploaded"
    assert jobs_progress.get_lecture_progress(lid)["status"] == "uploaded"


# ---------------------------------------------------------- course teardown

def test_purge_course_clears_every_scoped_table(Session):
    a = _lecture(Session, status="ready")
    b = _lecture(Session, status="ready")
    with Session() as s:
        s.add(models.TranscriptSegment(lecture_id=a, idx=0, start_s=0.0, end_s=1.0, text="x"))
        s.add(models.Passage(lecture_id=a, idx=0, title="t", kind="explain",
                             start_s=0.0, end_s=1.0))
        s.add(models.LectureLink(lecture_id=b, source_name="A", target_name="B"))
        s.add(models.Clip(lecture_id=a, concept_name="A", start_s=0.0,
                          end_s=1.0, path="a.mp4", ok=1))
        s.add(models.GraphNode(course_id="c1", name="A"))
        s.add(models.GraphEdge(course_id="c1", source="A", target="B", confidence=0.9))
        q = models.ConceptItem(course_id="c1", concept="A", question="q", order=0)
        s.add(q)
        s.flush()
        s.add(models.QuizResponse(course_id="c1", student_id="s", question_id=q.id,
                                  concept="A", correct=1, latency_s=0.5))
        s.commit()

    assert jobs_purge.purge_course("c1") == 2

    with Session() as s:
        assert s.query(models.Lecture).count() == 0
        assert s.query(models.TranscriptSegment).count() == 0
        assert s.query(models.Passage).count() == 0
        assert s.query(models.LectureLink).count() == 0
        assert s.query(models.Clip).count() == 0
        assert s.query(models.GraphNode).count() == 0
        assert s.query(models.GraphEdge).count() == 0
        assert s.query(models.ConceptItem).count() == 0
        assert s.query(models.QuizResponse).count() == 0


# ------------------------------------------------------------- query helpers

def test_query_lecture_segments_are_time_ordered_across_lectures(Session):
    a = _lecture(Session, status="ready")
    b = _lecture(Session, status="ready")
    with Session() as s:
        s.add(models.TranscriptSegment(lecture_id=a, idx=0, start_s=9.0, end_s=10.0, text="late"))
        s.add(models.TranscriptSegment(lecture_id=b, idx=0, start_s=1.0, end_s=2.0, text="early"))
        s.commit()
    with Session() as s:
        segs = queries.lecture_segments(s, "c1")
        assert [seg.text for seg in segs] == ["early", "late"]


def test_query_clips_first_ok_wins(Session):
    a = _lecture(Session, status="ready")
    with Session() as s:
        s.add(models.Clip(lecture_id=a, concept_name="A", start_s=0.0, end_s=1.0,
                          path="ok.mp4", ok=0))
        s.add(models.Clip(lecture_id=a, concept_name="A", start_s=0.0, end_s=1.0,
                          path="later-good.mp4", ok=1))
        s.commit()
    assert queries.clips_by_concept("c1") == {"A": "later-good.mp4"}