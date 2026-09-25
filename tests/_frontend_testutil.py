"""Shared helpers for the AppTest (Level-2) frontend suites."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STUDENT_APP = str(REPO / "frontend" / "student_app.py")
FACULTY_APP = str(REPO / "frontend" / "faculty_app.py")

COURSE_SUMMARIES = [{
    "course_id": "ml1", "total_lectures": 1, "ready_lectures": 1,
    "total_concepts": 3, "has_graph": True, "node_count": 3, "edge_count": 2,
}]


def ready_lecture(lecture_id: int = 1, title: str = "Lec 1") -> dict:
    return {"id": lecture_id, "course_id": "ml1", "title": title,
            "status": "ready", "created_at": "2026-01-01T00:00:00",
            "error": None, "processed_at": None}


def find_button(at, label):
    for b in at.button:
        if b.label == label:
            return b
    raise AssertionError(
        f"button {label!r} not found; got {[x.label for x in at.button]}"
    )


def markdown_texts(at):
    return [m.value for m in at.markdown]


def any_markdown_contains(at, needle):
    for m in at.markdown:
        if needle in m.value:
            return True
    return False


DEFAULT_CLIENT = {
    "course_summaries": lambda: list(COURSE_SUMMARIES),
    "list_lectures": lambda: [ready_lecture()],
    "get": lambda path, params=None, timeout=30: None,
    "post": lambda path, **kw: None,
    "delete": lambda path, timeout=30: None,
    "course_stats": lambda course_id, ttl=300.0: None,
    "course_graph": lambda course_id, ttl=300.0: None,
    "lecture_detail": lambda lecture_id, ttl=300.0: None,
    "lecture_clips": lambda lecture_id, ttl=60.0: None,
    "usage": lambda ttl=30.0: None,
    "upload_media": lambda *a, **k: {"id": 1, "status": "uploaded"},
    "course_snapshot": lambda course_id, ttl=5.0: None,
}


def install_backend(monkeypatch, overrides=None):
    """Monkeypatch every ``frontend.client`` function the apps touch so AppTest
    runs are fully hermetic. ``overrides`` replaces individual fns."""
    from frontend import client as client_mod

    merged = dict(DEFAULT_CLIENT)
    if overrides:
        merged.update(overrides)

    def make_fn(name, fn):
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    for name, fn in merged.items():
        target = getattr(client_mod, name)
        impl = make_fn(name, fn)
        monkeypatch.setattr(client_mod, name, impl)
    return client_mod