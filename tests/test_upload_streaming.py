"""Tests for the two-step upload flow: POST /lectures (no file) + the streamed
PUT /lectures/{id}/media with live progress.

Hermetic: throwaway SQLite DB (tests/conftest.py) + monkeypatched background
transcribe worker (no real Whisper/network). Reuses the smoke clip media so a
real file exists on disk.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.api import jobs  # noqa: E402
from backend.api.jobs import progress as jobs_progress  # noqa: E402
from backend.config import MAX_UPLOAD_MB, MEDIA_ROOT_DIR  # noqa: E402
from backend.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def _patch_worker(monkeypatch):
    scheduled = []

    def fake_process(lecture_id, backend=None, job_id=None):
        # job_id is added by the C3 enqueue path; recording it lets the tests
        # below assert the worker is bound to a durable job row.
        scheduled.append({"id": lecture_id, "backend": backend, "job_id": job_id})

    monkeypatch.setattr(jobs, "process_lecture", fake_process)
    return scheduled


@pytest.fixture
def client():
    return TestClient(app)


def _create(client, course_id="ml", whisper_backend=None):
    data = {"course_id": course_id}
    if whisper_backend is not None:
        data["whisper_backend"] = whisper_backend
    r = client.post("/lectures", data=data)
    assert r.status_code == 201
    return r.json()


def test_two_step_create_then_stream(client, _patch_worker):
    lec = _create(client, whisper_backend="groq")
    lid = lec["id"]
    assert lec["status"] == "uploaded"
    # nothing scheduled yet (no media)
    assert _patch_worker == []

    body = b"A" * (2 * 1024 * 1024)
    r = client.put(
        f"/lectures/{lid}/media",
        params={"filename": "lec.mp4", "whisper_backend": "groq"},
        headers={"Content-Length": str(len(body))}, content=body,
    )
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "uploaded"  # worker flips it to transcribing
    # media written to disk under data/raw
    dest = MEDIA_ROOT_DIR / f"lec{lid}_lec.mp4"
    assert dest.read_bytes() == body
    # transcription scheduled with the backend the frontend re-sent on the PUT,
    # and bound to a durable job row (C3)
    assert len(_patch_worker) == 1
    call = _patch_worker[0]
    assert call["id"] == lid and call["backend"] == "groq"
    assert isinstance(call["job_id"], int) and call["job_id"] > 0
    from backend.api import job_registry as registry
    job = registry.get_job(call["job_id"])
    assert job is not None and job["kind"] == "transcribe"
    assert job["lecture_id"] == lid
    dest.unlink(missing_ok=True)
    jobs_progress._finish(lid)


def test_media_put_publishes_uploading_progress(client, _patch_worker):
    lid = _create(client)["id"]
    body = b"B" * 4096
    client.put(
        f"/lectures/{lid}/media", params={"filename": "b.mp4"},
        headers={"Content-Length": str(len(body))}, content=body,
    )
    snap = jobs_progress.get_lecture_progress(lid)
    assert snap["stage"] == "uploading"
    assert snap["progress_pct"] == 100
    jobs_progress._finish(lid)
    (MEDIA_ROOT_DIR / f"lec{lid}_b.mp4").unlink(missing_ok=True)


def test_media_put_requires_uploaded_status(client):
    # flip the create's "uploaded" row to "ready" so the PUT guard triggers
    from backend.models.db import Lecture, SessionLocal

    lec = _create(client)
    with SessionLocal() as db:
        row = db.get(Lecture, lec["id"])
        row.status = "ready"
        db.commit()
    r = client.put(
        f"/lectures/{lec['id']}/media", params={"filename": "x.mp4"},
        headers={"Content-Length": "5"}, content=b"12345",
    )
    assert r.status_code == 409
    assert "must be 'uploaded'" in r.json()["detail"]


def test_media_put_404_unknown_lecture(client):
    r = client.put(
        "/lectures/999999/media", params={"filename": "x.mp4"},
        headers={"Content-Length": "5"}, content=b"12345",
    )
    assert r.status_code == 404


def test_media_put_rejects_bad_extension(client):
    lid = _create(client)["id"]
    r = client.put(
        f"/lectures/{lid}/media", params={"filename": "x.exe"},
        headers={"Content-Length": "5"}, content=b"12345",
    )
    assert r.status_code == 400
    assert "Unsupported file type" in r.json()["detail"]


def test_media_put_requires_content_length(client):
    lid = _create(client)["id"]
    r = client.put(
        f"/lectures/{lid}/media", params={"filename": "x.mp4"},
        content=iter([b"12345"]),  # generator body -> chunked, no Content-Length
    )
    assert r.status_code == 400
    assert "Content-Length" in r.json()["detail"]


def test_media_put_413_on_oversize(client, monkeypatch):
    monkeypatch.setattr("backend.api.routes.lectures.MAX_UPLOAD_MB", 1)  # 1 MiB
    lid = _create(client)["id"]
    body = b"C" * (2 * 1024 * 1024)
    r = client.put(
        f"/lectures/{lid}/media", params={"filename": "big.mp4"},
        headers={"Content-Length": str(len(body))}, content=body,
    )
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]
    # no media left behind
    assert not (MEDIA_ROOT_DIR / f"lec{lid}_big.mp4").exists()