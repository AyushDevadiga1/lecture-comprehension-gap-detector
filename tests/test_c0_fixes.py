"""C0 regression tests — plan/ENGINE2_REBUILD_PLAN.md.

Each test pins one defect from the C0 checkpoint:

  * a job whose lecture never leaves ``uploaded`` re-rendered the page every
    0.5-1.5s until the 6-hour deadline (backend progress.py:68 returns the raw
    lecture status, so the fallback is non-terminal forever);
  * ``_UPLOADS`` was an unlocked process-global written by the upload daemon
    thread and read by the per-session script thread;
  * action buttons stayed clickable while their job was in flight, so a double
    click queued duplicate work;
  * ``PIPELINE_SEMAPHORE`` was documented as covering all four heavy stages but
    only transcription acquired it, and a plain BoundedSemaphore would deadlock
    on the extract -> graph chain at LECGAP_MAX_PIPELINE_JOBS=1;
  * ``POST /quizzes`` deleted and recreated the course's questions, so two
    concurrent generations silently discarded each other's rows.
"""

import threading
import time
import types

import pytest

from frontend import client as client_mod
from frontend import state
# every symbol this module exercises now lives in the shell panel; aliasing it
# as `components` keeps the test names readable
from frontend.panels import shell as components


# --------------------------------------------------------------- session state

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


class _St:
    """Minimal stand-in for the st.* calls render_progress_cards makes."""

    def __init__(self):
        self.bars = []
        self.captions = []
        self.warnings = []
        self.errors = []
        self.successes = []
        self.buttons = {}
        self.reruns = 0

    def progress(self, *a, **k):
        self.bars.append((a, k))

    def caption(self, *a, **k):
        self.captions.append(a[0] if a else "")

    def warning(self, *a, **k):
        self.warnings.append(a[0] if a else "")

    def error(self, *a, **k):
        self.errors.append(a[0] if a else "")

    def success(self, *a, **k):
        self.successes.append(a[0] if a else "")

    def button(self, label, **k):
        return self.buttons.get(label, False)

    def rerun(self):
        self.reruns += 1
        raise RuntimeError("rerun")  # st.rerun() raises to break the script


@pytest.fixture
def fake_st(monkeypatch):
    st = _St()
    monkeypatch.setattr(components, "st", st)
    monkeypatch.setattr(components.time, "sleep", lambda *_a, **_k: None)
    return st


def _poll(monkeypatch, payload, times=None):
    """Make client.get return `payload`; count how often it was called."""
    calls = {"n": 0}
    seq = list(times) if times else None

    def _get(path, params=None, timeout=30):
        calls["n"] += 1
        if seq is not None:
            return seq[min(calls["n"] - 1, len(seq) - 1)]
        return payload

    monkeypatch.setattr(client_mod, "get", _get)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a, **_k: None)
    return calls


# ------------------------------------------------------- C0.1 stall detection

def test_stalled_job_on_uploaded_lecture_stops_rerendering(monkeypatch, sess, fake_st):
    """The 6-hour flicker, generic branch.

    backend/api/jobs/progress.py:68 reports the lecture's raw status, so a row
    that never leaves `uploaded` is non-terminal forever. A job of any kind
    other than `upload` falls through to the generic branch, which used to
    `keep` + `want_rerun` until the 6h deadline.
    """
    components.start_job("ml", 5, "Upload + transcribe", kind="transcribe")
    _poll(monkeypatch, {"status": "uploaded", "stage": "uploaded",
                        "progress_pct": 50, "detail": "Lecture status: uploaded"})

    for _ in range(components._MAX_STALLED_POLLS + 3):
        try:
            components.render_progress_cards()
        except RuntimeError:
            pass
        if fake_st.warnings:
            break

    assert fake_st.warnings, "a stalled job must warn instead of spinning"
    assert "no progress" in fake_st.warnings[0]
    assert state.get("jobs", "items") == [], "the stalled job must be dropped"


def test_hanging_upload_thread_stalls_instead_of_spinning(monkeypatch, sess, fake_st):
    """A registry entry whose thread never finishes is the other real path."""
    components.start_job("ml", 6, "Upload + transcribe", kind="upload")
    with components._UPLOADS_LOCK:
        components._UPLOADS[6] = {
            "thread": None, "cancel": threading.Event(),
            "done": threading.Event(),           # never set -> still pending
            "ok": {"ok": False, "error": None}, "title": "T",
        }
    _poll(monkeypatch, {"status": "uploaded", "stage": "uploaded",
                        "progress_pct": 0, "detail": "Upload starting..."})

    for _ in range(components._MAX_STALLED_POLLS + 3):
        try:
            components.render_progress_cards()
        except RuntimeError:
            pass
        if fake_st.warnings:
            break
    with components._UPLOADS_LOCK:
        components._UPLOADS.pop(6, None)

    assert fake_st.warnings
    assert "not starting" in fake_st.warnings[0]
    assert state.get("jobs", "items") == []


def test_missing_upload_entry_fails_fast(monkeypatch, sess, fake_st):
    """No registry entry means the client-side thread is already gone.

    This path must error on the first poll, not spin: there is nothing left to
    wait for.
    """
    components.start_job("ml", 7, "Upload + transcribe", kind="upload")
    with components._UPLOADS_LOCK:
        components._UPLOADS.pop(7, None)
    _poll(monkeypatch, {"status": "uploaded", "stage": "uploaded",
                        "progress_pct": 0, "detail": "Upload starting..."})

    try:
        components.render_progress_cards()
    except RuntimeError:
        pass
    assert fake_st.errors, "an upload with no live thread must error immediately"
    assert state.get("jobs", "items") == []


def test_progressing_job_keeps_polling(monkeypatch, sess, fake_st):
    """A job whose stage/pct actually advances must not be called stalled."""
    components.start_job("ml", 3, "Extract", kind="extract")
    steps = [
        {"status": "extracting", "stage": "extracting", "progress_pct": 10},
        {"status": "extracting", "stage": "extracting", "progress_pct": 40},
        {"status": "extracting", "stage": "building_graph", "progress_pct": 75},
        {"status": "extracting", "stage": "building_graph", "progress_pct": 90},
    ]
    _poll(monkeypatch, None, times=steps)
    for _ in steps:  # exactly as many polls as there are advancing steps
        try:
            components.render_progress_cards()
        except RuntimeError:
            pass
    assert not fake_st.warnings
    assert len(state.get("jobs", "items")) == 1
    # and the recorded fingerprint tracks the latest observation
    assert state.get("jobs", "items")[0]["fingerprint"] == "extracting|building_graph|90"


def test_slow_but_steady_stage_is_not_cut_off(monkeypatch, sess, fake_st):
    """A local-Whisper transcribe legitimately sits on one stage for a long time.

    The cutoff is about a job that never reports anything new; a job that
    reports a *changing* updated_at is fine, and a job that repeats the same
    stage just under the limit is still fine.
    """
    components.start_job("ml", 2, "Transcribe", kind="transcribe")
    payload = {"status": "transcribing", "stage": "local_transcribing",
               "progress_pct": 50, "detail": "Decoding", "elapsed_s": 10}
    _poll(monkeypatch, payload)
    for _ in range(components._MAX_STALLED_POLLS - 1):
        try:
            components.render_progress_cards()
        except RuntimeError:
            pass
    assert not fake_st.warnings
    assert len(state.get("jobs", "items")) == 1


def test_stall_cutoff_is_not_too_tight_for_long_transcription():
    """Guard the constant itself: 40 polls x ~1.5s backoff is ~1 minute of
    wall clock only if polling were instant, but the real loop sleeps between
    polls, so assert it is comfortably above a typical short stage and well
    below the 6h deadline."""
    assert 20 <= components._MAX_STALLED_POLLS <= 120
    assert components._MAX_STALLED_POLLS < components._JOB_DEADLINE_S / 60


# ------------------------------------------------------------ C0.2 _UPLOADS lock

def test_uploads_registry_is_lock_guarded():
    assert hasattr(components, "_UPLOADS_LOCK")
    assert isinstance(components._UPLOADS_LOCK, type(threading.RLock()))


def test_concurrent_begin_upload_registers_exactly_one(monkeypatch, sess):
    """Two sessions racing the same lecture must not both start a transfer."""
    release = threading.Event()

    def slow_upload(*a, **k):
        release.wait(2.0)
        return {"id": 1, "status": "uploaded"}

    monkeypatch.setattr(client_mod, "upload_media", slow_upload)
    monkeypatch.setattr(client_mod, "take_last_error", lambda: None)

    results = []
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        results.append(components.begin_upload("ml", 9, "T", "f.mp4", b"x"))

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    release.set()

    assert results.count(False) >= 1, "the duplicate upload must be refused"
    with components._UPLOADS_LOCK:
        assert 9 in components._UPLOADS


def test_upload_status_pops_entry_under_lock(monkeypatch, sess):
    """_upload_status must not leave a half-read entry behind."""
    monkeypatch.setattr(client_mod, "upload_media", lambda *a, **k: {"id": 1})
    monkeypatch.setattr(client_mod, "take_last_error", lambda: None)
    components.begin_upload("ml", 11, "T", "f.mp4", b"x")
    # the first terminal observation is the one that pops the entry
    result = (False, False, None)
    for _ in range(200):
        result = components._upload_status(11, "upload")
        if result[0]:
            break
        time.sleep(0.01)
    done, ok, err = result
    assert done and ok and err is None
    with components._UPLOADS_LOCK:
        assert 11 not in components._UPLOADS


# --------------------------------------------------------- C0.3 active_job gate

def test_active_job_reports_live_kinds(sess):
    assert components.active_job(3) is False
    components.start_job("ml", 3, "Extract", kind="extract")
    assert components.active_job(3) is True
    assert components.active_job(3, kinds=("extract", "graph")) is True
    assert components.active_job(3, kinds=("graph",)) is False
    assert components.active_job(4) is False


def test_active_job_ignores_other_lectures(sess):
    components.start_job("ml", 3, "Extract", kind="extract")
    assert components.active_job(3, kinds=("clips",)) is False
    assert components.active_job(99) is False


def test_active_job_handles_empty_list(sess):
    assert components.active_job(1) is False
