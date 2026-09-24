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