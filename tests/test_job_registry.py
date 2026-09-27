"""C2 — the job registry: persistence, restart recovery, locking, SSE, and the
non-blocking quiz endpoint.

The process-memory progress store this replaces could not answer "is the job
still alive?", "what happened to it when the server died?", or "who else is
watching it?". These tests pin the answers.
"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api.jobs import registry
from backend.main import app
from backend.models.db import Job, SessionLocal

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_jobs():
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    registry.reset_locks_for_tests()
    yield
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    registry.reset_locks_for_tests()


# ------------------------------------------------------------- create/read

def test_create_job_persists_and_is_readable():
    job_id = registry.create_job("quiz", course_id="ml", title="Quiz for ml")
    assert isinstance(job_id, int) and job_id > 0
    job = registry.get_job(job_id)
    assert job["kind"] == "quiz"
    assert job["status"] == "queued"
    assert job["course_id"] == "ml"
    assert job["terminal"] is False
    # it is in the DB, not in process memory
    with SessionLocal() as db:
        assert db.get(Job, job_id) is not None


def test_progress_updates_are_visible():
    job_id = registry.create_job("transcribe", course_id="ml", lecture_id=1)
    registry.update_job(job_id, stage="transcribing", progress_pct=40,
                        status="running")
    job = registry.get_job(job_id)
    assert job["status"] == "running"
    assert job["stage"] == "transcribing"
    assert job["progress_pct"] == 40
    assert job["started_at"] is not None


def test_progress_pct_is_clamped():
    job_id = registry.create_job("x", course_id="ml")
    registry.update_job(job_id, progress_pct=999)
    assert registry.get_job(job_id)["progress_pct"] == 100
    registry.update_job(job_id, progress_pct=-5)
    assert registry.get_job(job_id)["progress_pct"] == 0


def test_finish_records_a_duration():
    job_id = registry.create_job("x", course_id="ml")
    registry.update_job(job_id, status="running")
    time.sleep(0.01)
    registry.finish_job(job_id, status="ready", detail="done")
    job = registry.get_job(job_id)
    assert job["status"] == "ready"
    assert job["terminal"] is True
    assert job["progress_pct"] == 100
    assert job["duration_s"] is not None and job["duration_s"] >= 0


def test_fail_job_keeps_the_error():
    job_id = registry.create_job("x", course_id="ml")
    registry.fail_job(job_id, "ffmpeg exploded")
    job = registry.get_job(job_id)
    assert job["status"] == "error"
    assert job["error"] == "ffmpeg exploded"
    assert job["terminal"] is True


def test_list_jobs_scopes_to_a_course():
    a = registry.create_job("x", course_id="ml")
    b = registry.create_job("x", course_id="prob")
    ids = [j["id"] for j in registry.list_jobs(course_id="ml")]
    assert a in ids and b not in ids
    everything = {j["id"] for j in registry.list_jobs()}
    assert {a, b} <= everything


def test_list_jobs_active_only_hides_settled():
    live = registry.create_job("x", course_id="ml")
    done = registry.create_job("x", course_id="ml")
    registry.finish_job(done, status="ready")
    active = {j["id"] for j in registry.list_jobs(course_id="ml",
                                                   active_only=True)}
    assert live in active
    assert done not in active


# --------------------------------------------------------- restart recovery

def test_recover_orphans_settles_jobs_left_running():
    """A job left `running` by a dead process is not running any more."""
    job_id = registry.create_job("transcribe", course_id="ml")
    registry.update_job(job_id, status="running", progress_pct=30)
    # backdate the heartbeat past the threshold
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
        db.commit()

    n = registry.recover_orphans()
    assert n >= 1
    job = registry.get_job(job_id)
    assert job["status"] == "orphaned"
    assert job["terminal"] is True
    assert "restart" in (job["error"] or "").lower()


def test_recover_orphans_leaves_recent_work_alone():
    """A quiet-but-alive job must not be called dead - a long ffmpeg re-encode
    publishes nothing for minutes."""
    job_id = registry.create_job("clips", course_id="ml")
    registry.update_job(job_id, status="running")
    assert registry.recover_orphans() == 0
    assert registry.get_job(job_id)["status"] == "running"


def test_recover_orphans_is_idempotent():
    job_id = registry.create_job("x", course_id="ml")
    registry.update_job(job_id, status="running")
    with SessionLocal() as db:
        db.get(Job, job_id).heartbeat_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()
    first = registry.recover_orphans()
    second = registry.recover_orphans()
    assert first >= 1
    assert second == 0, "a second pass must not re-count settled jobs"


def test_boot_path_runs_recovery():
    """main.py calls recover_orphans() at import; assert the hook is wired."""
    import backend.main as m
    text = open(m.__file__, encoding="utf-8").read()
    assert "recover_orphans()" in text


# ------------------------------------------------------------- course lock

def test_course_lock_refuses_a_second_holder():
    lock = registry.acquire_course("ml")
    try:
        with pytest.raises(registry.CourseBusy):
            registry.acquire_course("ml")
    finally:
        lock.release()
    # released, so it can be taken again
    registry.acquire_course("ml").release()


def test_course_lock_is_per_course():
    a = registry.acquire_course("ml")
    b = registry.acquire_course("prob")
    a.release()
    b.release()


def test_course_lock_allows_empty_course_id():
    lock = registry.acquire_course(None)
    lock.release()


# ----------------------------------------------------------------- HTTP API

def test_get_jobs_lists_across_sessions():
    """The point of the registry: a second browser sees the first one's jobs."""
    a = registry.create_job("transcribe", course_id="ml", title="A")
    b = registry.create_job("graph", course_id="ml", title="B")
    r = client.get("/jobs", params={"course_id": "ml"})
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()["jobs"]}
    assert {a, b} <= ids


def test_get_job_by_id():
    job_id = registry.create_job("x", course_id="ml")
    r = client.get(f"/jobs/{job_id}")
    assert r.status_code == 200 and r.json()["id"] == job_id


def test_get_job_404s():
    assert client.get("/jobs/999999").status_code == 404


def test_jobs_rejects_a_bad_course_id():
    assert client.get("/jobs", params={"course_id": "bad id!"}).status_code == 422


def test_cancel_a_queued_job():
    job_id = registry.create_job("x", course_id="ml")
    r = client.post(f"/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["terminal"] is True


def test_cancel_refuses_a_finished_job():
    job_id = registry.create_job("x", course_id="ml")
    registry.finish_job(job_id, status="ready")
    r = client.post(f"/jobs/{job_id}/cancel")
    assert r.status_code == 409


def test_stream_emits_sse_with_a_snapshot():
    """Driven through the generator, not an endless HTTP body."""
    import asyncio

    from backend.api.routes.jobs import event_stream

    registry.create_job("transcribe", course_id="ml", title="live")

    async def take(n):
        out = []
        async for chunk in event_stream(course_id="ml", interval_s=0.01):
            out.append(chunk)
            if len(out) >= n:
                break
        return out

    chunks = asyncio.run(take(2))
    assert "retry: 2000" in chunks[0]
    assert "event: jobs" in chunks[1]
    payload = chunks[1].split("data: ", 1)[1].strip()
    jobs = json.loads(payload)
    assert jobs and jobs[0]["kind"] == "transcribe"


def test_stream_sends_a_keepalive_when_nothing_changed():
    import asyncio

    from backend.api.routes.jobs import event_stream

    registry.create_job("x", course_id="ml")

    async def take(n):
        out = []
        async for chunk in event_stream(course_id="ml", interval_s=0.01):
            out.append(chunk)
            if len(out) >= n:
                break
        return out

    chunks = asyncio.run(take(3))
    assert "event: jobs" in chunks[1]
    assert chunks[2].startswith(": keep-alive"), chunks[2]


def test_stream_route_is_registered():
    """Header/streaming behaviour is covered through the generator above; a
    TestClient GET against an endless body would block forever, so assert the
    route exists instead."""
    spec = app.openapi()
    assert "/jobs/stream" in spec["paths"]
    assert "get" in spec["paths"]["/jobs/stream"]


# ------------------------------------------------------- async quiz endpoint

@pytest.fixture
def stub_quiz_generation(monkeypatch):
    """Never call the real LLM from a registry test.

    ``TestClient`` runs BackgroundTasks synchronously after the response, so an
    unstubbed POST /quizzes/jobs would block the test for minutes and spend real
    quota. Also seeds a course, because the suite runs against conftest's
    hermetic temp database rather than the live one.
    """
    from backend.api.routes import quizzes
    from backend.models.db import Concept, Lecture

    with SessionLocal() as db:
        if not db.query(Concept).filter(Concept.course_id == "prob").count():
            lec = Lecture(course_id="prob", title="seed", status="ready")
            db.add(lec)
            db.commit()
            lid = lec.id
            for name in ("Alpha", "Beta", "Gamma"):
                db.add(Concept(course_id="prob", lecture_id=lid, name=name,
                               start_s=0.0, end_s=10.0))
            db.commit()

    calls = []
    monkeypatch.setattr(quizzes, "_create_quiz",
                        lambda c, s, m=None: calls.append((c, s, m)))
    return calls


def test_quiz_job_endpoint_returns_202_immediately(stub_quiz_generation):
    r = client.post("/quizzes/jobs",
                    json={"course_id": "prob", "student_id": "s1",
                          "max_questions": 2})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_id"] > 0
    # the background body ran and settled the job
    assert stub_quiz_generation == [("prob", "s1", 2)]
    job = registry.get_job(body["job_id"])
    assert job["status"] == "ready"
    assert job["terminal"] is True


def test_quiz_job_records_a_failure(monkeypatch):
    from backend.api.routes import quizzes

    def boom(c, s, m=None):
        raise RuntimeError("groq said gsk_SECRET_TOKEN was invalid")

    monkeypatch.setattr(quizzes, "_create_quiz", boom)
    r = client.post("/quizzes/jobs", json={"course_id": "prob",
                                           "student_id": "s1"})
    assert r.status_code == 202
    job = registry.get_job(r.json()["job_id"])
    assert job["status"] == "error"
    assert job["terminal"] is True
    # M2: the record names the failure but never carries provider internals
    assert "RuntimeError" in job["error"]
    assert "gsk_" not in job["error"], "secret leaked into a persisted row"


def test_quiz_job_releases_the_course_lock_afterwards(stub_quiz_generation):
    """A failed generation must not wedge the course's lock."""
    from backend.api.routes import quizzes

    client.post("/quizzes/jobs", json={"course_id": "prob", "student_id": "s1"})
    lock = quizzes._quiz_lock("prob")
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_quiz_job_404s_without_concepts():
    r = client.post("/quizzes/jobs",
                    json={"course_id": "no-such-course", "student_id": "s1"})
    assert r.status_code == 404


def test_quiz_job_409s_when_one_is_already_running(stub_quiz_generation):
    from backend.api.routes import quizzes

    quizzes._quiz_lock("prob").acquire(blocking=False)
    try:
        r = client.post("/quizzes/jobs",
                        json={"course_id": "prob", "student_id": "s1"})
        assert r.status_code == 409
    finally:
        quizzes._quiz_lock("prob").release()


def test_sync_quiz_endpoint_still_exists():
    """The blocking endpoint is kept for compatibility; it just isn't the one
    the UI should use any more."""
    paths = {p for p in app.openapi()["paths"]}
    assert "/quizzes" in paths
    assert "/quizzes/jobs" in paths
