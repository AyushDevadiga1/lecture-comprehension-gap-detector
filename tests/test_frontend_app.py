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

    def __getattr__(self, name):
        return self._any


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


# ------------------------------------------------------------- course options

def test_course_options_from_summaries(app_module):
    app_module._get = lambda *a, **kw: [
        {"course_id": "ml2", "total_lectures": 1},
        {"course_id": "ml1", "total_lectures": 3},
    ]
    assert app_module._course_options() == ["ml1", "ml2"]


def test_course_options_falls_back_to_lectures(app_module):
    def fake_get(path, **kw):
        if path == "/courses":
            return None  # summaries unavailable
        return [{"course_id": "b"}, {"course_id": "a"}, {"course_id": "b"}]

    app_module._get = fake_get
    assert app_module._course_options() == ["a", "b"]