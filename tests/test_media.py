"""Tests for the clip media endpoint (backend/api/routes/media.py).

Serves real files from data/processed/clips/<lecture_id>/ with Range support,
so this suite writes a scratch clip under CLIPS_BASE_DIR (cleaned up after) and
points the app at a throwaway SQLite DB to keep the dev lecgap.db untouched.
"""

import os
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ["LECGAP_DATABASE_URL"] = "sqlite:///data/test_media_lecgap.db"

from backend.config import CLIPS_BASE_DIR  # noqa: E402
from backend.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_LEC_ID = "49000"
_CLIP = CLIPS_BASE_DIR / _LEC_ID / "cliptest.mp4"
_DB = REPO / "data" / "test_media_lecgap.db"


@pytest.fixture(autouse=True)
def _scratch_clip():
    _CLIP.parent.mkdir(parents=True, exist_ok=True)
    _CLIP.write_bytes(b"x" * 1000)
    yield
    shutil.rmtree(_CLIP.parent, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app)


def test_streams_full_clip(client):
    r = client.get(f"/media/clips/{_LEC_ID}/cliptest.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.content == b"x" * 1000


def test_range_request_returns_206(client):
    r = client.get(
        f"/media/clips/{_LEC_ID}/cliptest.mp4",
        headers={"Range": "bytes=0-99"},
    )
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 0-99/1000"
    assert r.content == b"x" * 100


def test_missing_file_404(client):
    r = client.get(f"/media/clips/{_LEC_ID}/nope.mp4")
    assert r.status_code == 404


def test_unknown_lecture_404(client):
    r = client.get("/media/clips/999999/x.mp4")
    assert r.status_code == 404


def test_dot_dot_filename_rejected(client):
    r = client.get(f"/media/clips/{_LEC_ID}/..")
    assert r.status_code == 404


def test_non_int_lecture_422(client):
    r = client.get("/media/clips/notanint/x.mp4")
    assert r.status_code == 422