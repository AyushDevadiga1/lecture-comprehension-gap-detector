"""Unit tests for frontend/components.py pieces that don't need Streamlit's
runtime: the multi-job monitor bookkeeping (start_job) — the single-slot
overwrite bug's regression test — and the stage guidance text."""

import types

import pytest

from frontend import components, state


class _SessionState:
    def __init__(self):
        self._d = {}

    def __contains__(self, key):
        return key in self._d

    def __getitem__(self, key):
        return self._d[key]

    def __setitem__(self, key, value):
        self._d[key] = value

    def __delitem__(self, key):
        del self._d[key]

    def pop(self, key, default=None):
        return self._d.pop(key, default)

    def keys(self):
        return self._d.keys()


@pytest.fixture
def sess(monkeypatch):
    ss = _SessionState()
    monkeypatch.setattr(state, "st", types.SimpleNamespace(session_state=ss))
    return ss


def test_start_job_adds_and_never_overwrites(sess):
    components.start_job("ml", 3, "Extract", kind="extract")
    components.start_job("ml", 5, "Transcription", kind="transcribe")
    items = state.get("jobs", "items")
    assert len(items) == 2  # second job does NOT drop the first (audit fix #6)
    assert {j["kind"] for j in items} == {"extract", "transcribe"}


def test_start_job_coalesces_identical_lecture_kind(sess):
    components.start_job("ml", 3, "Extract", kind="extract")
    components.start_job("ml", 3, "Extract again", kind="extract")
    items = state.get("jobs", "items")
    assert len(items) == 1
    assert items[0]["title"] == "Extract again"


def test_jobs_accumulate_across_courses(sess):
    components.start_job("ml", 3, "Extract", kind="extract")
    components.start_job("cv", 8, "Clips", kind="clips")
    assert len(state.get("jobs", "items")) == 2


def test_job_guidance_hints_and_elapsed():
    text = components._job_guidance("clips", 125)
    assert "Cutting concept clips" in text
    assert "2m 05s" in text
    bare = components._job_guidance("whatnow", 0)
    assert "whatnow" in bare


# --------------------------------------------------------------- usage summary

_USAGE_SERVICES = {
    "groq.chat": {"model": "m", "remaining_requests": 14391,
                  "remaining_tokens": 1499000, "reset_in_s": 907, "calls": 1},
    "groq.whisper": {"model": "w", "remaining_requests": 90,
                     "reset_in_s": 300, "calls": 1},
    "local": {"available": True, "unlimited": True, "ffmpeg_ok": True},
    "ollama": {"reachable": False},
}


def test_usage_summary_renders_services_and_honest_unknowns():
    lines = components._usage_summary(_USAGE_SERVICES)
    joined = "\n".join(lines)
    assert "Groq chat: 14,391 req left" in joined
    assert "1,499,000 tok left" in joined
    assert "Groq whisper: 90 req left" in joined
    assert "Local Whisper: available" in joined

    unknown = components._usage_summary(
        {"groq.chat": {}, "groq.whisper": {}, "local": {"available": True},
         "ollama": {"reachable": False}},
        availability={"groq_configured": True},
    )
    assert any("Groq chat: no usage data yet" in ln for ln in unknown)
    assert any("Groq whisper: no usage data yet" in ln for ln in unknown)
    assert any("Local Whisper: available" in ln for ln in unknown)


def test_usage_summary_estimate_uses_live_duration():
    lines = components._usage_summary(_USAGE_SERVICES, duration_s=900.0)
    estimate = [ln for ln in lines if ln.startswith("This lecture")]
    assert len(estimate) == 1
    # 900s / 300s chunks = 3 whisper requests = 3.3% of 90 remaining = 30 left
    assert "≈ 3 Groq requests" in estimate[0]
    assert "3.3% of remaining" in estimate[0]
    assert "≈ 30 more lectures like this" in estimate[0]

    no_duration = components._usage_summary(_USAGE_SERVICES, duration_s=None)
    assert not any(ln.startswith("This lecture") for ln in no_duration)


def test_duplicate_lecture_detects_matching_stem_or_name(monkeypatch):
    from frontend import client as client_mod

    lectures = [
        {"id": 4, "course_id": "ml", "title": "lec1.mp4"},
        {"id": 5, "course_id": "ml", "title": "lec2"},
        {"id": 6, "course_id": "other", "title": "lec1.mp4"},
    ]
    monkeypatch.setattr(client_mod, "list_lectures", lambda ttl=60.0: lectures)
    assert components.duplicate_lecture("ml", "lec1.mp4") == 4
    assert components.duplicate_lecture("ml", "lec2.mp4") == 5  # stem match
    assert components.duplicate_lecture("ml", "brand-new.mp4") is None
    assert components.duplicate_lecture("ml", None) is None


# ----------------------------------------------------------- upload registry

def test_begin_upload_registers_job_and_resolves_ok(monkeypatch, sess):
    from frontend import client as client_mod

    monkeypatch.setattr(client_mod, "upload_media",
                        lambda *a, **k: {"id": 3, "status": "uploaded"})
    assert components.begin_upload("ml", 3, "Upload + transcribe",
                                   "f.mp4", b"x" * 10) is True
    assert state.get("jobs", "items")[0]["kind"] == "upload"

    entry = components._UPLOADS[3]
    assert entry["done"].wait(2)
    done, ok, err = components._upload_status(3, "upload")
    assert done and ok and err is None
    assert 3 not in components._UPLOADS  # registry cleaned after handling


def test_begin_upload_surfaces_failure_detail(monkeypatch, sess):
    from frontend import client as client_mod

    monkeypatch.setattr(client_mod, "upload_media", lambda *a, **k: None)
    client_mod.LAST_ERROR = {"kind": "http", "status": 413,
                             "detail": "too big", "path": "/media"}
    components.begin_upload("ml", 4, "U", "f.mp4", b"x")
    entry = components._UPLOADS[4]
    assert entry["done"].wait(2)
    done, ok, err = components._upload_status(4, "upload")
    assert done and not ok and err == "too big"


def test_cancel_upload_sets_the_stop_event(monkeypatch, sess):
    import threading

    from frontend import client as client_mod

    release = threading.Event()
    monkeypatch.setattr(client_mod, "upload_media",
                        lambda *a, **k: release.wait(2) or {"id": 5})
    components.begin_upload("ml", 5, "U", "f.mp4", b"x")
    try:
        assert components.cancel_upload(5) is True
        assert components._UPLOADS[5]["cancel"].is_set()
    finally:
        release.set()
        assert components._UPLOADS[5]["done"].wait(2)