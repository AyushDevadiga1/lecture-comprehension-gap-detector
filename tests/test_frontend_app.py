"""Hermetic tests for the Streamlit entrypoint helpers (frontend/app.py).

Importing app.py executes its top-level UI script (st.set_page_config, the
sidebar block, tab contexts), so this module installs neutral `streamlit` +
`requests` stubs in sys.modules *before* importing the app and then drives the
pure-ish helper functions directly: the error-safe HTTP wrappers (_get/_post/
_delete), progress clamping (_wrap_progress), the course-option fallback
(_course_options) and the background-job poll loop (_wait_progress).

The real Streamlit runtime wiring is exercised end-to-end by
scripts/smoke_drive.py against a live backend — not duplicable here.
"""

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_STUB_KEYS = ("streamlit", "streamlit.components", "streamlit.components.v1",
              "requests")


class _Any:
    """Universal streamlit widget stub: callable, context-manager, iterable,
    subscriptable, and deliberately falsy so no `if st.button(...)` branch runs
    at import."""

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return self

    def __getitem__(self, key):
        return self

    def __setitem__(self, key, value):
        pass

    def __contains__(self, key):
        return True

    def __iter__(self):
        return iter([self, self])  # st.tabs(["Student", "Faculty"]) unpack

    def __bool__(self):
        return False

    def __str__(self):
        return ""

    def __repr__(self):
        return "<stub>"


class _StreamlitStub(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self._any = _Any()
        self.cache_data = _cache_stub()

    def __getattr__(self, name):
        return self._any


def _cache_stub():
    """Pass-through stand-in for st.cache_data used by @-decoration in app.py.

    The real TTL/hash caching is Streamlit's job (exercised live by
    scripts/smoke_drive.py); here the decorator must simply keep the wrapped
    function callable and expose `.clear()` for the refresh-button wiring.
    """

    def dec(func):
        def wrapper(*a, **kw):
            return func(*a, **kw)

        wrapper.clear = lambda *a, **kw: None
        wrapper.clear_all = lambda *a, **kw: None
        return wrapper

    def cache_data(func=None, **kw):
        return dec(func) if func is not None else dec

    return cache_data


class _ReqError(Exception):
    pass


class _ReqTimeout(_ReqError):
    pass


def _install_stubs():
    st = _StreamlitStub()
    sys.modules["streamlit"] = st
    comp = types.ModuleType("streamlit.components")
    comp.v1 = types.ModuleType("streamlit.components.v1")
    comp.v1.html = lambda *a, **kw: None
    sys.modules["streamlit.components"] = comp
    sys.modules["streamlit.components.v1"] = comp.v1

    req = types.ModuleType("requests")
    req.RequestException = _ReqError
    req.Timeout = _ReqTimeout
    req.get = lambda *a, **kw: (_ for _ in ()).throw(_ReqError("no network"))
    req.post = lambda *a, **kw: (_ for _ in ()).throw(_ReqError("no network"))
    req.delete = lambda *a, **kw: (_ for _ in ()).throw(_ReqError("no network"))
    sys.modules["requests"] = req


@pytest.fixture(scope="session")
def app_module():
    """Import frontend.app once against neutral streamlit/requests stubs.

    The stubs are removed from sys.modules right after import: app.py's
    top-level UI script ran against them at import time, and the module keeps
    its own ``st``/``requests`` references as globals for the helpers. Leaving
    them in sys.modules would shadow the real packages for every other test in
    the session (torch's import-time frame introspection broke on them). The
    imported app module object itself stays cached as the fixture return value.
    """
    saved = {k: sys.modules.get(k) for k in _STUB_KEYS}
    _install_stubs()
    import frontend.app as app

    for k in _STUB_KEYS:
        if saved[k] is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = saved[k]
    return app


def _recorder():
    calls = []
    return calls, lambda msg: calls.append(msg)


# ----------------------------------------------------------------- error-safe HTTP

def test_get_returns_json_on_success(app_module):
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"course_id": "ml1"}

    app_module.requests.get = lambda *a, **kw: FakeResp()
    assert app_module._get("/courses") == {"course_id": "ml1"}


def test_get_timeout_is_silent_and_returns_none(app_module):
    calls, err = _recorder()
    app_module.st.error = err

    def slow(*a, **kw):
        raise app_module.requests.Timeout("too slow")

    app_module.requests.get = slow
    assert app_module._get("/x", timeout=1, silent=True) is None
    assert calls == []  # silent: no on-screen error
    assert app_module._get("/x", timeout=1) is None
    assert len(calls) == 1 and "timed out" in calls[0]


def test_get_network_and_http_errors_surface_notes(app_module):
    calls, err = _recorder()
    app_module.st.error = err

    def boom(*a, **kw):
        raise app_module.requests.RequestException("connection refused")

    app_module.requests.get = boom
    assert app_module._get("/x") is None
    assert len(calls) == 1 and "connection refused" in calls[0]

    class HttpErr:
        def raise_for_status(self):
            raise app_module.requests.RequestException("HTTP 500")

    app_module.requests.get = lambda *a, **kw: HttpErr()
    assert app_module._get("/x") is None
    assert any("HTTP 500" in c for c in calls)


def test_post_shows_backend_detail_on_4xx(app_module):
    calls, err = _recorder()
    app_module.st.error = err

    class Rejected:
        status_code = 422
        text = "raw body"

        def json(self):
            return {"detail": "bad concept list"}

    app_module.requests.post = lambda *a, **kw: Rejected()
    assert app_module._post("/quizzes", json={}) is None
    assert calls == ["bad concept list"]


def test_post_returns_json_on_success(app_module):
    class Created:
        status_code = 201

        def json(self):
            return {"id": 7}

    app_module.requests.post = lambda *a, **kw: Created()
    assert app_module._post("/lectures", json={}) == {"id": 7}


def test_delete_success_and_404(app_module):
    calls, err = _recorder()
    app_module.st.error = err

    class Gone:
        status_code = 404
        text = "Course 'x' not found"

        def json(self):
            return {"detail": "Course 'x' not found"}

    app_module.requests.delete = lambda *a, **kw: Gone()
    assert app_module._delete("/courses/x") is None
    assert calls == ["Course 'x' not found"]

    class Ok:
        status_code = 200

        def json(self):
            return {"deleted": True}

    app_module.requests.delete = lambda *a, **kw: Ok()
    assert app_module._delete("/courses/x") == {"deleted": True}


# ------------------------------------------------------------------ progress

def test_wrap_progress_clamps_to_100(app_module):
    calls = []

    class PBar:
        def progress(self, pct, text=None):
            calls.append((pct, text))

    app_module._wrap_progress(PBar(), 150, "done")
    assert calls == [(100, "done")]


def test_wrap_progress_legacy_streamlit_fallback(app_module):
    captured = []

    class OldBar:
        def progress(self, pct, text=None):
            if text is not None:
                raise TypeError("no text kwarg")
            captured.append(pct)

    app_module.st.caption = captured.append
    app_module._wrap_progress(OldBar(), 50, "halfway")
    assert captured == [50, "halfway"]


def test_wait_progress_returns_when_ready(app_module):
    payload = {"status": "ready", "progress_pct": 100, "detail": "Done."}
    app_module._get = lambda *a, **kw: payload
    assert app_module._wait_progress(1) == payload


def test_wait_progress_surfaces_error_status(app_module):
    app_module._get = lambda *a, **kw: {"status": "error", "detail": "boom"}
    out = app_module._wait_progress(1)
    assert out["status"] == "error" and out["detail"] == "boom"


def test_wait_progress_times_out_with_non_terminal_status(app_module):
    app_module._get = lambda *a, **kw: {"status": "extracting",
                                        "progress_pct": 42, "detail": "running"}
    assert app_module._wait_progress(1, timeout=0) is None


class _SessionState:
    """Minimal dict-like stand-in for st.session_state in the monitor tests."""

    def __init__(self):
        self._d = {}

    def get(self, key, default=None):
        return self._d.get(key, default)

    def pop(self, key, default=None):
        return self._d.pop(key, default)

    def __setitem__(self, key, value):
        self._d[key] = value


def test_start_job_records_monitor_binding(app_module):
    ss = _SessionState()
    app_module.st.session_state = ss
    app_module._start_job(9, "Clip cutting", after="clips_list")
    job = ss.get("lecgap_job")
    assert job["lecture_id"] == 9
    assert job["title"] == "Clip cutting"
    assert job["after"] == "clips_list"
    assert job["deadline"] > 0


def test_monitor_no_job_is_noop(app_module):
    app_module.st.session_state = _SessionState()
    app_module.st.success = lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("must not render without a job"))
    app_module._monitor_progress()  # must not raise


def test_monitor_queued_shows_warning_without_rerun(app_module):
    app_module.st.session_state = _SessionState()
    app_module.st.session_state["lecgap_job"] = {
        "lecture_id": 4, "title": "t", "after": None, "deadline": 1e18
    }
    warned = []
    reruns = []
    app_module.st.warning = warned.append
    app_module.st.rerun = lambda *a, **kw: reruns.append(True)
    app_module._get = lambda *a, **kw: None  # no progress yet
    app_module._monitor_progress()
    assert warned and "queued" in warned[0].lower()
    assert reruns == []


def test_monitor_ready_pops_job_and_invalidates_caches(app_module):
    ss = _SessionState()
    ss["lecgap_job"] = {"lecture_id": 4, "title": "t", "after": None,
                        "deadline": 1e18}
    app_module.st.session_state = ss
    clearee = []
    app_module.st.success = lambda *a, **kw: None
    app_module.st.progress = lambda *a, **kw: None
    for fn in (app_module._course_summaries, app_module._list_lectures,
               app_module._lecture_detail):
        clearee.append(set())

        def clear(rec=clearee[-1], *a, **kw):
            rec.add(True)

        fn.clear = clear
    app_module._get = lambda *a, **kw: {"status": "ready", "progress_pct": 100,
                                        "detail": "Done.", "stage": "ready"}
    app_module._monitor_progress()
    assert ss.get("lecgap_job") is None
    assert all(rec for rec in clearee)  # every data cache invalidated


def test_monitor_ready_with_clips_followup_lists_files(app_module):
    ss = _SessionState()
    ss["lecgap_job"] = {"lecture_id": 4, "title": "t", "after": "clips_list",
                        "deadline": 1e18}
    app_module.st.session_state = ss
    written = []
    app_module.st.write = written.append
    app_module.st.expander = lambda *a, **kw: app_module.st._any
    app_module.st.code = lambda *a, **kw: None
    app_module.st.success = lambda *a, **kw: None
    app_module.st.progress = lambda *a, **kw: None

    def fake_get(path, **kw):
        if "progress" in path:
            return {"status": "ready", "progress_pct": 100, "detail": "Done."}
        if "clips" in path:
            return {"clips": [
                {"ok": 1, "path": r"data/processed/clips/4/clip_1.mp4"},
                {"ok": 0, "path": ""},
                {"ok": 1, "path": r"data/processed/clips/4/clip_2.mp4"},
            ]}

    app_module._get = fake_get
    app_module._monitor_progress()
    assert any("2 clips" in str(w) for w in written)


def test_monitor_error_pops_job_and_shows_message(app_module):
    ss = _SessionState()
    ss["lecgap_job"] = {"lecture_id": 4, "title": "t", "after": None,
                        "deadline": 1e18}
    app_module.st.session_state = ss
    errs = []
    app_module.st.error = errs.append
    app_module._get = lambda *a, **kw: {"status": "error", "progress_pct": 0,
                                        "detail": "boom"}
    app_module._monitor_progress()
    assert ss.get("lecgap_job") is None
    assert errs == ["boom"]


def test_monitor_in_flight_polls_and_reruns_adaptively(app_module):
    ss = _SessionState()
    ss["lecgap_job"] = {"lecture_id": 4, "title": "t", "after": None,
                        "deadline": 1e18}
    app_module.st.session_state = ss
    app_module.st.progress = lambda *a, **kw: None

    delays = []
    reruns = []

    def fake_sleep(s):
        delays.append(s)

    app_module.time.sleep = fake_sleep
    app_module.st.rerun = lambda *a, **kw: reruns.append(True)
    app_module._get = lambda *a, **kw: {"status": "transcribing",
                                        "progress_pct": 40, "detail": "tick",
                                        "stage": "transcribing", "elapsed_s": 5}

    app_module._monitor_progress()  # fast short stage -> 0.5s backoff
    assert delays == [0.5]
    assert reruns == [True]

    delays.clear()
    reruns.clear()
    app_module._get = lambda *a, **kw: {"status": "working",
                                        "progress_pct": 40, "detail": "tick",
                                        "stage": "clips", "elapsed_s": 5}
    app_module._monitor_progress()  # long unadvancing stage -> 1.5s backoff
    assert delays == [1.5]
    assert reruns == [True]


def test_monitor_deadline_expiry_stops_polling(app_module):
    ss = _SessionState()
    ss["lecgap_job"] = {"lecture_id": 4, "title": "t", "after": None,
                        "deadline": -1}  # already expired
    app_module.st.session_state = ss
    warned = []
    reruns = []
    app_module.st.warning = warned.append
    app_module.st.rerun = lambda *a, **kw: reruns.append(True)
    app_module._get = lambda *a, **kw: {"status": "transcribing",
                                        "progress_pct": 4, "detail": "x",
                                        "stage": "probing"}
    app_module._monitor_progress()
    assert warned and "timed out" in warned[0].lower()
    assert reruns == []
    assert ss.get("lecgap_job") is None


def test_job_guidance_hints_and_elapsed(app_module):
    text = app_module._job_guidance("clips", 125)
    assert "Cutting concept clips" in text
    assert "2m 05s" in text
    bare = app_module._job_guidance("whatnow", 0)
    assert "whatnow" in bare


def test_list_lectures_and_detail_are_cached_passthroughs(app_module):
    def fake_get(path, **kw):
        if path == "/lectures":
            return [{"id": 1, "course_id": "ml1"}]
        if path == "/lectures/1":
            return {"id": 1, "segments": [], "concepts": []}

    app_module._get = fake_get
    assert app_module._list_lectures() == [{"id": 1, "course_id": "ml1"}]
    assert app_module._lecture_detail(1)["id"] == 1
    app_module._list_lectures.clear()
    app_module._lecture_detail.clear()


def test_invalidate_data_caches_clears_every_cache(app_module):
    cleared = []

    class Cached:
        def clear(self):
            cleared.append(True)

    saved = (app_module._course_summaries, app_module._list_lectures,
             app_module._lecture_detail)
    app_module._course_summaries, app_module._list_lectures = Cached(), Cached()
    app_module._lecture_detail = Cached()
    try:
        app_module._invalidate_data_caches()
        assert cleared == [True, True, True]
    finally:
        (app_module._course_summaries, app_module._list_lectures,
         app_module._lecture_detail) = saved


def test_post_forwards_params_to_requests(app_module):
    captured = []

    app_module.requests.post = lambda *a, **kw: captured.append(kw) or _Ok()

    class _Ok:
        status_code = 200

        def json(self):
            return {"queued": True}

    assert app_module._post("/courses/ml1/graph",
                            params={"lecture_id": 7}) == {"queued": True}
    assert captured and captured[0]["params"] == {"lecture_id": 7}


# ------------------------------------------------------------- course options

def test_course_summaries_passes_through_get(app_module):
    summaries = [{"course_id": "ml1", "total_lectures": 2}]
    app_module._get = lambda *a, **kw: summaries
    assert app_module._course_summaries() == summaries


def test_course_summaries_expose_clear_for_refresh_button(app_module):
    app_module._get = lambda *a, **kw: None
    app_module._course_summaries()  # must not raise
    app_module._course_summaries.clear()
    app_module._course_summaries.clear_all()


def test_course_options_from_summaries(app_module):
    summaries = [
        {"course_id": "ml2", "total_lectures": 1},
        {"course_id": "ml1", "total_lectures": 3},
    ]
    app_module._course_summaries = lambda: summaries
    assert app_module._course_options() == ["ml1", "ml2"]


def test_course_options_falls_back_to_lectures(app_module):
    def fake_get(path, **kw):
        if path == "/courses":
            return None  # summaries unavailable
        return [{"course_id": "b"}, {"course_id": "a"}, {"course_id": "b"}]

    app_module._get = fake_get
    app_module._course_summaries = lambda: app_module._get("/courses", silent=True)
    assert app_module._course_options() == ["a", "b"]