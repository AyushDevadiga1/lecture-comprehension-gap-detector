"""Level-2 AppTest flows for the Student dashboard (frontend/student_app.py).

The regression tests reproduce the audit's production failures and pin the
fixes: a background-job rerun must never wipe an in-flight quiz, the upload
course is locked to the sidebar, a stale quiz submit degrades to a friendly
message, and multi-job monitor cards resolve without dropping each other.
"""

import pytest
from streamlit.testing.v1 import AppTest

from frontend import client

from tests._frontend_testutil import (
    STUDENT_APP,
    ready_lecture,
    find_button,
    install_backend,
    any_markdown_contains,
)

QUIZ_PAYLOAD = {
    "quiz_id": 1, "course_id": "ml1", "student_id": "demo-student",
    "questions": [
        {"id": 101, "concept": "Alpha", "question": "What is Alpha?",
         "options": ["a1", "a2", "a3"]},
    ],
}

SUBMIT_OK = {
    "quiz_id": 101, "student_id": "demo-student", "score": 1, "total": 1,
    "remediation": [
        {"concept": "Beta", "failed": True,
         "clip": r"data/processed/clips/1/beta.mp4"},
    ],
    "feedback": [
        {"question_id": 101, "concept": "Alpha", "correct": True,
         "selected": "a1", "answer": "a1", "explanation": "right",
         "rationale": None},
    ],
}


@pytest.fixture(autouse=True)
def _clean_last_error():
    client.LAST_ERROR = None
    yield
    client.LAST_ERROR = None


def _run():
    return AppTest.from_file(STUDENT_APP).run()


def test_sidebar_and_process_panels_render(monkeypatch):
    install_backend(monkeypatch)
    at = _run()
    assert any(s.label == "Active course" for s in at.selectbox)
    for label in ("Upload + transcribe", "Extract concepts + build graph",
                  "Generate quiz"):
        assert any(b.label == label for b in at.button)


def test_upload_course_is_locked_when_course_exists(monkeypatch):
    install_backend(monkeypatch)
    at = _run()
    text_yields = [t.label for t in at.get("text_input")]
    # No free-text course field when a course is selected — no silent drift.
    assert "Course ID (creates the course)" not in text_yields


def test_quiz_survives_a_plain_rerun(monkeypatch):
    """Regression for audit fix #1: a background-job rerun must never wipe the
    student's in-flight quiz (questions live in session state, not a local)."""

    def post(path, **kw):
        return QUIZ_PAYLOAD if path == "/quizzes" else SUBMIT_OK

    install_backend(monkeypatch, {"post": post})
    at = _run()
    find_button(at, "Generate quiz").click().run()

    assert len(at.radio) == 1  # the question rendered
    assert "What is Alpha?" == at.radio[0].label

    at.run()  # simulate any unrelated rerun (job-poll, click elsewhere)
    assert len(at.radio) == 1  # quiz STILL present — the audit bug is gone


def test_quiz_submit_scores_and_shows_remediation(monkeypatch):
    def post(path, **kw):
        return QUIZ_PAYLOAD if path == "/quizzes" else SUBMIT_OK

    install_backend(monkeypatch, {"post": post})
    at = _run()
    find_button(at, "Generate quiz").click().run()
    find_button(at, "Submit answers").click().run()

    assert any_markdown_contains(at, "Score: 1/1")
    assert any_markdown_contains(at, "**Beta**")


def test_stale_quiz_submit_degrades_gracefully(monkeypatch):
    """Audit fix #9: server regenerated the course's questions while the student
    was answering -> friendly 'generate again', never a raw traceback."""

    def post(path, **kw):
        if path == "/quizzes":
            return QUIZ_PAYLOAD
        client.LAST_ERROR = {"kind": "http", "status": 404,
                             "detail": "Question 101 not found", "path": path}
        return None

    install_backend(monkeypatch, {"post": post})
    at = _run()
    find_button(at, "Generate quiz").click().run()
    find_button(at, "Submit answers").click().run()

    assert any("regenerated" in e.value.lower() for e in at.error)

    at.run()  # questions cleared on the next render after the stale-404 fallback
    assert len(at.radio) == 0


def test_background_job_card_resolves_on_ready(monkeypatch):
    """A started job renders a live card, lands on a terminal 'ready', and is
    cleared — all without looping reruns."""

    def post(path, **kw):
        if path == "/lectures/1/concepts":
            return {"id": 1}  # truthy -> job registered
        return None

    def get(path, params=None, timeout=30):
        if path == "/lectures/1/progress":
            return {"status": "ready", "progress_pct": 100, "detail": "Done.",
                    "stage": "ready", "elapsed_s": 5}
        return None

    install_backend(monkeypatch, {"post": post, "get": get})
    at = _run()
    find_button(at, "Extract concepts + build graph").click().run()
    at.run()  # progress poll tick -> job lands on 'ready', card shows
    assert any("Done." in s.value for s in at.success)

    at.run()  # terminal card is gone; nothing re-queues
    assert not any("Done." in s.value for s in at.success)


def test_bootstrap_creates_first_course_without_courses(monkeypatch):
    install_backend(monkeypatch, {
        "course_summaries": lambda: [],
        "list_lectures": lambda: [],
    })
    at = _run()
    assert any(t.label == "Course ID (creates the course)"
               for t in at.get("text_input"))
    assert any("first course" in w.value.lower() for w in at.warning)


def test_clips_followup_lists_cut_files_after_ready(monkeypatch):
    """Parity flow: 'Cut concept clips' registers a job whose 'ready' runs the
    clip-list follow-up (kept from the old app, now multi-job)."""

    def post(path, **kw):
        if path == "/lectures/1/clips":
            return {"lecture_id": 1, "status": "queued"}
        return None

    def get(path, params=None, timeout=30):
        if path == "/lectures/1/progress":
            return {"status": "ready", "progress_pct": 100, "detail": "Done.",
                    "stage": "ready", "elapsed_s": 3}
        if path == "/lectures/1/clips":
            return {"lecture_id": 1, "status": "ready", "clips": [
                {"id": 1, "concept_name": "Alpha", "start_s": 0.0, "end_s": 1.0,
                 "path": "data/processed/clips/1/alpha.mp4", "ok": True,
                 "error": None},
            ]}
        return None

    install_backend(monkeypatch, {"post": post, "get": get})
    at = _run()
    find_button(at, "Cut concept clips").click().run()
    at.run()  # poll tick -> ready + follow-up list
    assert any_markdown_contains(at, "1 clips cut")