"""Tests for the API-usage store + `GET /usage` + progress duration_s.

Hermetic: points the app at a throwaway SQLite DB (dev lecgap.db untouched)
and drives the usage store + endpoint directly.
"""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ["LECGAP_DATABASE_URL"] = "sqlite:///data/test_usage_lecgap.db"

from backend.api import usage  # noqa: E402
from backend.api.jobs import progress as jobs_progress  # noqa: E402
from backend.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    with usage._lock:
        usage._state = {"groq.chat": {}, "groq.whisper": {}}
        usage._total_calls = {"groq.chat": 0, "groq.whisper": 0}
    yield


@pytest.fixture
def client():
    return TestClient(app)


# ----------------------------------------------------------------- parse

def test_parse_reset_seconds():
    assert usage.parse_reset_seconds("60s") == 60.0
    assert usage.parse_reset_seconds("7m18.5s") == pytest.approx(438.5)
    assert usage.parse_reset_seconds("1h2m") == pytest.approx(3720.0)
    assert usage.parse_reset_seconds(None) is None
    assert usage.parse_reset_seconds("") is None


# ----------------------------------------------------------------- record

def test_record_groq_captures_headers():
    headers = {
        "x-ratelimit-limit-requests": "14400",
        "x-ratelimit-remaining-requests": "14391",
        "x-ratelimit-limit-tokens": "1500000",
        "x-ratelimit-remaining-tokens": "1499000",
        "x-ratelimit-reset-requests": "1h7m30.5s",
    }
    usage.record_groq("groq.chat", "m-20b", headers)
    snap = usage.snapshot()["services"]["groq.chat"]
    assert snap["model"] == "m-20b"
    assert snap["remaining_requests"] == 14391
    assert snap["remaining_tokens"] == 1499000
    assert snap["calls"] == 1
    assert snap["reset_in_s"] == pytest.approx(4050.5)
    assert snap["last_checked"] is not None


def test_record_groq_handles_missing_headers():
    usage.record_groq("groq.whisper", "whisper-v3", None)
    snap = usage.snapshot()["services"]["groq.whisper"]
    assert snap["model"] == "whisper-v3"
    assert "remaining_requests" not in snap
    assert snap["calls"] == 1


def test_record_groq_429_fallback_path():
    """The 429 branch may pass only exc.response.headers — same store path."""
    usage.record_groq("groq.chat", "m", {"x-ratelimit-remaining-requests": "1"})
    assert usage.snapshot()["services"]["groq.chat"]["remaining_requests"] == 1


# ----------------------------------------------------------------- endpoint

def test_get_usage_shape(client):
    usage.record_groq(
        "groq.chat", "gpt-oss-20b",
        {"x-ratelimit-remaining-requests": "5", "x-ratelimit-remaining-tokens": "100"},
    )
    r = client.get("/usage")
    assert r.status_code == 200
    body = r.json()
    services = body["services"]
    assert set(services) == {"groq.chat", "groq.whisper", "local", "ollama"}
    assert services["groq.chat"]["remaining_requests"] == 5
    assert services["groq.chat"]["remaining_tokens"] == 100
    assert services["groq.whisper"].get("remaining_requests") is None
    assert "model" in services["groq.chat"] and "calls" in services["groq.chat"]
    assert "ffmpeg_ok" in services["local"]
    assert "unlimited" in services["local"] and services["local"]["unlimited"] is True
    assert "reachable" in services["ollama"]
    assert "availability" in body
    assert "groq_configured" in body["availability"]


# ------------------------------------------------------------- progress duration

def test_progress_holds_duration_until_job_finishes():
    jobs_progress.update_lecture_progress(1, "probing", 5, "probing...",
                                          duration_s=900.0)
    snap = jobs_progress.get_lecture_progress(1)
    assert snap["duration_s"] == 900.0
    assert snap["stage"] == "probing"

    jobs_progress._finish(1)
    assert jobs_progress.get_lecture_progress(1)["duration_s"] is None