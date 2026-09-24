"""Level-2 AppTest flows for the Faculty dashboard (frontend/faculty_app.py).

Pins the audit fixes: loaded stats and the DAG persist across plain reruns
(background-job polls no longer erase them), and the timeline renders its
coverage HTML for a ready lecture.
"""

import pytest
from streamlit.testing.v1 import AppTest

from frontend import client

from tests._frontend_testutil import (
    FACULTY_APP,
    ready_lecture,
    find_button,
    install_backend,
    any_markdown_contains,
)

STATS = {
    "course_id": "ml1",
    "heatmap": [
        {"concept": "Alpha", "wrong": 2, "attempts": 5, "rate": 0.4},
        {"concept": "Gamma", "wrong": 0, "attempts": 2, "rate": 0.0},
    ],
    "divergence": [
        {"concept": "Beta", "taught_idx": 1, "learned_idx": 3, "gap": 2},
        {"concept": "Lambda", "taught_idx": None, "learned_idx": None, "gap": 0},
    ],
    "taught_order": ["Alpha", "Beta"],
    "learned_order": ["Alpha", "Beta"],
}

GRAPH = {
    "course_id": "ml1",
    "nodes": ["Alpha", "Beta"],
    "edges": [{"source": "Alpha", "target": "Beta", "confidence": 0.9}],
    "node_count": 2, "edge_count": 1, "is_dag": True,
    "topological_order": ["Alpha", "Beta"],
}

DETAIL = {
    "id": 1, "course_id": "ml1", "title": "Lec 1", "status": "ready",
    "segments": [{"idx": 0, "start_s": 0.0, "end_s": 10.0, "text": "intro"}],
    "concepts": [{"id": 1, "name": "Alpha", "source": "spoken", "implicit": False,
                  "start_s": 0.0, "end_s": 10.0}],
}


@pytest.fixture(autouse=True)
def _clean_last_error():
    client.LAST_ERROR = None
    yield
    client.LAST_ERROR = None


def _run():
    # pyvis (dag_html) imports/jinja-compiles on first render — exceed the 3s
    # AppTest default so the timeout reflects user time, not import cost.
    return AppTest.from_file(FACULTY_APP, default_timeout=60).run()


def test_stats_render_and_persist_across_rerun(monkeypatch):
    install_backend(monkeypatch, {"course_stats": lambda cid, ttl=300.0: STATS})
    at = _run()
    find_button(at, "Load course stats").click().run()

    assert any_markdown_contains(at, "Wrong-answer rates")
    assert any_markdown_contains(at, "Alpha: 2/5 (40%)")
    assert any_markdown_contains(at, "taught #—")  # None indices render as —

    at.run()  # a background poll rerun must NOT erase the loaded stats
    assert any_markdown_contains(at, "Wrong-answer rates")


def test_dag_renders_and_persists_across_rerun(monkeypatch):
    install_backend(monkeypatch, {"course_graph": lambda cid, ttl=300.0: GRAPH})
    at = _run()
    find_button(at, "Render DAG").click().run()

    assert any_markdown_contains(at, "2 nodes · 1 edges")
    assert any_markdown_contains(at, "acyclic (DAG)")
    frames = at.get("iframe")
    assert len(frames) == 1  # dag_html embedded via st.iframe
    assert "Alpha" in frames[0].proto.srcdoc
    assert "vis-network" in frames[0].proto.srcdoc

    at.run()
    assert any_markdown_contains(at, "acyclic (DAG)")  # persisted, not wiped


def test_dag_empty_state_hints(monkeypatch):
    empty = dict(GRAPH, nodes=[], node_count=0, edge_count=0,
                 topological_order=[])
    install_backend(monkeypatch, {"course_graph": lambda cid, ttl=300.0: empty})
    at = _run()
    find_button(at, "Render DAG").click().run()
    assert any("No nodes yet" in i.value for i in at.info)


def test_timeline_renders_coverage_html(monkeypatch):
    install_backend(monkeypatch, {
        "list_lectures": lambda: [ready_lecture()],
        "lecture_detail": lambda lid, ttl=300.0: DETAIL,
    })
    at = _run()
    assert any(s.label == "Lecture" for s in at.selectbox)
    frames = at.get("iframe")
    assert len(frames) >= 1  # lecture_html timeline embedded via st.iframe
    rendered = frames[-1].proto.srcdoc
    assert "1 concepts" in rendered and "Alpha" in rendered


def test_no_ready_lecture_info(monkeypatch):
    install_backend(monkeypatch, {"list_lectures": lambda: []})
    at = _run()
    assert any("No ready lecture" in i.value for i in at.info)