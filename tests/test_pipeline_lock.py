"""F3 — the per-course advisory lock, wired into the lecture pipeline routes.

`acquire_course` / `release_course` / `CourseBusy` have existed in
`job_registry.py` since the job registry landed, with unit tests, and were called
from **no route at all**. That is the missing wiring the 2026-09-29 diagnosis
called "the single change that would have prevented this incident": one user
clicked *Extract Concepts* three times inside ninety seconds and got three
concurrent workers on one lecture.

The subtle part, and the reason this file spends more tests on release than on
refusal: a `BackgroundTask` runs *after* the response is sent. A lock taken in
the route and released when the route returns is free again before a single row
is written, so the second request would be admitted and both jobs would run
concurrently anyway. The lock has to be held for the duration of the *work*, and
released in a `finally` — because the workers this protects are exactly the ones
that crash.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import db as models


@pytest.fixture(autouse=True)
def _clean_locks():
    """The registry's locks are module-global; a leaked one breaks the next test."""
    from backend.api import job_registry as registry

    registry.reset_locks_for_tests()
    yield
    registry.reset_locks_for_tests()


@pytest.fixture
def client_and_session(monkeypatch):
    from backend.api import queries
    from backend.api.jobs import (
        clips as jobs_clips,
        extract as jobs_extract,
        graph as jobs_graph,
        progress as jobs_progress,
        purge as jobs_purge,
        transcribe as jobs_transcribe,
    )
    from backend.api.routes import courses, lectures
    from backend.main import app
    from fastapi.testclient import TestClient

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    for mod in (lectures, courses, queries, jobs_progress, jobs_transcribe,
                jobs_extract, jobs_clips, jobs_graph, jobs_purge):
        monkeypatch.setattr(mod, "SessionLocal", Session)
    monkeypatch.setattr("backend.api.job_registry.SessionLocal", Session)
    return TestClient(app), Session


def _ready_lecture(Session, course_id="ml1", title="L"):
    with Session() as s:
        lec = models.Lecture(course_id=course_id, title=title, status="ready")
        s.add(lec)
        s.commit()
        return lec.id


# ------------------------------------------------------------- the refusal

def test_second_extract_while_one_is_in_flight_returns_409(client_and_session, monkeypatch):
    """The headline behaviour, exercised as real concurrency rather than by
    pre-acquiring the lock — a real request, a real held lock, a real 409."""
    from backend.api import job_registry as registry
    from backend.api.routes import lectures as lectures_mod

    client, Session = client_and_session
    lid = _ready_lecture(Session)

    started = threading.Event()
    finish = threading.Event()

    def blocking_worker(lecture_id, job_id=None):
        started.set()
        finish.wait(10)
        # The worker runs on Starlette's background-task thread, which
        # TestClient joins before returning the response.

    monkeypatch.setattr(lectures_mod.jobs, "extract_concepts_worker", blocking_worker)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, f"/lectures/{lid}/concepts")
        assert started.wait(10), "the first worker never started, so nothing is locked"

        second = client.post(f"/lectures/{lid}/concepts")
        assert second.status_code == 409
        assert "ml1" in second.json()["detail"]
        assert "already has a heavy job running" in second.json()["detail"]

        finish.set()
        assert first.result(timeout=15).status_code == 200

    # ...and the refusal must not have leaked the lock.
    assert registry._course_lock("ml1").locked() is False


def test_a_refused_request_creates_no_job_row(client_and_session, monkeypatch):
    """A 409 must be a refusal, not a job that nobody will ever run."""
    from backend.api import job_registry as registry
    from backend.api.routes import lectures as lectures_mod

    client, Session = client_and_session
    lid = _ready_lecture(Session)
    registry.acquire_course("ml1")
    try:
        r = client.post(f"/lectures/{lid}/concepts")
        assert r.status_code == 409
        assert registry.list_jobs(course_id="ml1") == []
    finally:
        registry.release_course("ml1")


def test_a_different_course_is_not_blocked(client_and_session, monkeypatch):
    from backend.api import job_registry as registry

    client, Session = client_and_session
    a = _ready_lecture(Session, course_id="ml1")
    b = _ready_lecture(Session, course_id="prob")

    registry.acquire_course("ml1")
    try:
        # The lock is per COURSE, not per lecture, so this is the whole point of
        # checking it: a busy course must not stall an unrelated one.
        assert client.post(f"/lectures/{b}/concepts").status_code == 200
    finally:
        registry.release_course("ml1")


# ------------------------------------------------------------ the lifetime

def _capturing_tasks():
    """A BackgroundTasks stand-in that records rather than runs."""
    from fastapi import BackgroundTasks

    bt = BackgroundTasks()
    return bt, bt.tasks


def test_the_lock_is_held_for_the_work_not_the_request(monkeypatch):
    """The regression this whole design guards.

    Acquire in the route, release in the worker: after `_enqueue` returns, the
    lock must still be held, because the work has not started yet.
    """
    from backend.api import job_registry as registry
    from backend.api.routes import lectures as lectures_mod

    bt, tasks = _capturing_tasks()
    monkeypatch.setattr(registry, "SessionLocal", registry.SessionLocal)

    lectures_mod._enqueue(bt, lambda *a, job_id=None: None, kind="extract",
                          lecture_id=1, course_id="held", title="t",
                          args=(1,), course_lock=True)
    try:
        assert registry._course_lock("held").locked() is True, (
            "the lock was released before the work ran, so a second request "
            "would be admitted while the first is still going"
        )
        assert len(tasks) == 1
    finally:
        registry.release_course("held")


def test_the_lock_is_released_after_the_work_completes(monkeypatch):
    from backend.api import job_registry as registry
    from backend.api.routes import lectures as lectures_mod

    bt, tasks = _capturing_tasks()
    ran = []

    def worker(lecture_id, job_id=None):
        ran.append(lecture_id)

    lectures_mod._enqueue(bt, worker, kind="extract", lecture_id=1,
                          course_id="finishes", title="t", args=(1,),
                          course_lock=True)
    assert registry._course_lock("finishes").locked() is True

    for task in tasks:
        task.func(*task.args, **task.kwargs)

    assert ran == [1]
    assert registry._course_lock("finishes").locked() is False


def test_the_lock_is_released_even_when_the_worker_crashes(monkeypatch):
    """The one that matters most, because the workers being protected are the
    ones that crash. Releasing only on the happy path turns a single failure
    into a course that can never run a heavy job again, for the life of the
    process."""
    from backend.api import job_registry as registry
    from backend.api.routes import lectures as lectures_mod

    bt, tasks = _capturing_tasks()

    def exploding_worker(lecture_id, job_id=None):
        raise RuntimeError("sqlite3.IntegrityError: FOREIGN KEY constraint failed")

    lectures_mod._enqueue(bt, exploding_worker, kind="extract", lecture_id=1,
                          course_id="crashes", title="t", args=(1,),
                          course_lock=True)

    with pytest.raises(RuntimeError):
        for task in tasks:
            task.func(*task.args, **task.kwargs)

    assert registry._course_lock("crashes").locked() is False, (
        "a crashed worker leaked the course lock; this course can now never "
        "accept another heavy job until restart"
    )


def test_a_request_that_never_schedules_its_work_releases_the_lock(monkeypatch):
    """If `create_job` or `add_task` raises after the lock was taken, the lock
    must not stay held — otherwise one malformed request bricks the course."""
    from backend.api import job_registry as registry
    from backend.api.routes import lectures as lectures_mod

    bt, _ = _capturing_tasks()

    def boom(*a, **k):
        raise RuntimeError("db is down")

    monkeypatch.setattr(registry, "create_job", boom)
    with pytest.raises(RuntimeError):
        lectures_mod._enqueue(bt, lambda *a, job_id=None: None, kind="extract",
                              lecture_id=1, course_id="never", title="t",
                              args=(1,), course_lock=True)
    assert registry._course_lock("never").locked() is False


# ------------------------------------------------------------ the wiring

def test_the_three_pipeline_routes_take_the_lock_and_uploads_do_not():
    """Stated as a source check because that is what it is: a policy about which
    routes are heavy.

    `concepts`, `clips` and `rerun` mutate rows that another job on the same
    course also touches, so they take the lock. The two upload paths do not,
    deliberately: a new lecture row does not exist yet, so there is nothing to
    contend over, and refusing an upload because some extraction is running
    would be a worse product than the race it prevents.
    """
    import ast
    import inspect

    from backend.api.routes import lectures as lectures_mod

    tree = ast.parse(inspect.getsource(lectures_mod))
    locked, unlocked = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "_enqueue"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        kind = kw.get("kind")
        kind = kind.value if isinstance(kind, ast.Constant) else "?"
        takes = isinstance(kw.get("course_lock"), ast.Constant) and kw["course_lock"].value
        (locked if takes else unlocked).add(kind)

    assert locked == {"extract", "clips", "transcribe"}, locked
    assert "transcribe" in unlocked, "the upload paths must stay unlocked"