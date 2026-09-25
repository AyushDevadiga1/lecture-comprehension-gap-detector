"""Hermetic unit tests for frontend/client.py — pure Python, no Streamlit.

``client`` imports real ``requests``; every HTTP path here is exercised through
an injected fake by monkeypatching ``client.requests.request`` (the single
transport seam) so no network is touched. Time is controllable via a fresh
``CacheStore(clock=...)``.
"""

import pytest

from frontend import client


class _Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class _Resp:
    def __init__(self, status_code=200, payload=None, text=None, json_raises=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else str(payload)
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise self._json_raises
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


@pytest.fixture
def transport(monkeypatch):
    """Replaces ``client.requests.request`` with a recorded fake."""

    def make(request_fn):
        calls = []

        def fake(method, url, timeout, headers, **kw):
            calls.append({"method": method, "url": url, "headers": headers, "kw": kw})
            resp = request_fn(method, url, timeout=timeout, headers=headers, **kw)
            if isinstance(resp, BaseException):
                raise resp
            return resp

        monkeypatch.setattr(client.requests, "request", fake)
        return calls

    return make


# ---------------------------------------------------------------- URL validation

def test_validated_api_url_rejects_non_http():
    for bad in ("ftp://host", "file:///etc/passwd", "127.0.0.1:8000", "", "http://"):
        with pytest.raises(ValueError):
            client.validated_api_url(bad)
    assert client.validated_api_url("https://api.example.com/") == "https://api.example.com"


# ---------------------------------------------------------------- transport

def test_get_success_returns_json_and_clears_error(transport):
    calls = transport(lambda *a, **kw: _Resp(200, {"course_id": "ml1"}))
    client.LAST_ERROR = {"kind": "http", "status": 500, "detail": "x", "path": "/x"}
    assert client.get("/courses") == {"course_id": "ml1"}
    assert client.LAST_ERROR is None
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/courses")


def test_get_4xx_records_detail_and_returns_none(transport):
    transport(lambda *a, **kw: _Resp(404, None, text="raw", payload=None))
    detail_resp = _Resp(404, {"detail": "Lecture not found"}, text="Lecture not found")

    def req(*a, **kw):
        return detail_resp

    transport(req)
    assert client.get("/lectures/9") is None
    err = client.take_last_error()
    assert err["kind"] == "http" and err["status"] == 404
    assert err["detail"] == "Lecture not found"


def test_get_timeout_returns_none(transport):
    transport(lambda *a, **kw: client.requests.Timeout("slow"))
    assert client.get("/x", timeout=1) is None
    assert client.take_last_error()["kind"] == "timeout"


def test_get_connection_error_retries_once(transport):
    calls = []
    seen = {}

    def req(method, url, timeout, headers, **kw):
        calls.append(True)
        if not seen.get("threw"):
            seen["threw"] = True
            return client.requests.ConnectionError("refused")
        return _Resp(200, {"ok": True})

    transport(req)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(client, "RETRY_DELAY_S", 0.0)
    monkey.setattr(client, "ENABLE_RETRY", True)
    try:
        assert client.get("/retry") == {"ok": True}
        assert len(calls) == 2
    finally:
        monkey.undo()


def test_get_connection_error_gives_up_after_retry(transport):
    def req(*a, **kw):
        return client.requests.ConnectionError("down")

    transport(req)
    monkey = pytest.MonkeyPatch()
    monkey.setattr(client, "RETRY_DELAY_S", 0.0)
    try:
        assert client.get("/down") is None
        assert client.take_last_error()["kind"] == "network"
    finally:
        monkey.undo()


def test_get_non_json_response_returns_none(transport):
    transport(lambda *a, **kw: _Resp(200, payload=None, json_raises=ValueError("no json")))
    assert client.get("/html") is None
    assert client.take_last_error()["kind"] == "json"


def test_post_success_and_4xx(transport):
    transport(lambda *a, **kw: _Resp(201, {"id": 7}))
    assert client.post("/lectures", json={}) == {"id": 7}
    assert client.take_last_error() is None

    transport(lambda *a, **kw: _Resp(409, {"detail": "must be 'ready'"}))
    assert client.post("/lectures/9/concepts") is None
    assert "must be 'ready'" in client.take_last_error()["detail"]


def test_delete_success_and_404(transport):
    transport(lambda *a, **kw: _Resp(200, {"deleted": True}))
    assert client.delete("/courses/ml") == {"deleted": True}
    transport(lambda *a, **kw: _Resp(404, {"detail": "Course 'x' not found"}))
    assert client.delete("/courses/x") is None
    assert "not found" in client.take_last_error()["detail"]


def test_auth_header_sent_when_key_set(transport, monkeypatch):
    calls = transport(lambda *a, **kw: _Resp(200, {"ok": True}))
    monkeypatch.setenv("LECGAP_API_KEY", "sekret")
    assert client._auth_headers()["X-API-Key"] == "sekret"
    assert client.get("/x") == {"ok": True}
    assert calls[0]["headers"].get("X-API-Key") == "sekret"
    monkeypatch.delenv("LECGAP_API_KEY", raising=False)
    assert client._auth_headers() == {}


# ----------------------------------------------------------------- CacheStore

def test_cache_loader_runs_once_until_ttl():
    clock = _Clock()
    store = client.CacheStore(clock=clock)
    hits = []

    def load():
        hits.append(1)
        return {"n": len(hits)}

    assert store.get("GET", "/courses", ttl=60.0, loader=load) == {"n": 1}
    assert store.get("GET", "/courses", ttl=60.0, loader=load) == {"n": 1}
    assert hits == [1]  # loader not called on the hit

    clock.advance(61)
    store.get("GET", "/courses", ttl=60.0, loader=load)
    assert len(hits) == 2  # expired -> reloaded


def test_cache_payloads_returned_as_copies():
    store = client.CacheStore()
    store.get("GET", "/x", loader=lambda: {"xs": []})
    got = store.get("GET", "/x", loader=lambda: {"should": "not-be-called"})
    got["xs"].append("poison")
    again = store.get("GET", "/x", loader=lambda: {"should": "not-be-called"})
    assert again["xs"] == []  # first mutation did not poison the cache


def test_cache_never_stores_none():
    store = client.CacheStore()
    calls = []

    def load():
        calls.append(1)
        return None

    store.get("GET", "/down", ttl=60.0, loader=load)
    store.get("GET", "/down", ttl=60.0, loader=load)
    assert calls == [1, 1]  # failures always reload


def test_cache_invalidate_and_keying():
    store = client.CacheStore()
    store.get("GET", "/courses", loader=lambda: {"a": 1})
    store.get("GET", "/lectures", loader=lambda: {"b": 2})
    store.get("GET", "/courses/ml/stats", params={"x": 1}, loader=lambda: {"c": 3})
    assert len(store) == 3
    store.invalidate("GET /courses")  # drops BOTH the list and the course-scoped key
    assert len(store) == 1  # only /lectures survives
    assert "GET /lectures" in store._store
    store.invalidate_all()
    assert len(store) == 0


# ------------------------------------------------------- module cached accessors

def test_course_summaries_go_through_cache_store(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(client, "_CACHE", client.CacheStore(clock=clock))
    calls = []

    def fake_get(path, params=None, timeout=30):
        calls.append(path)
        return [{"course_id": "ml1", "total_lectures": 1}]

    monkeypatch.setattr(client, "get", fake_get)
    assert client.course_summaries() == [{"course_id": "ml1", "total_lectures": 1}]
    assert client.course_summaries() == [{"course_id": "ml1", "total_lectures": 1}]
    assert calls == ["/courses"]  # one HTTP call, memoized


def test_invalidate_for_course_clears_course_and_lecture_namespaces(monkeypatch):
    clock = _Clock()
    store = client.CacheStore(clock=clock)
    monkeypatch.setattr(client, "_CACHE", store)
    monkeypatch.setattr(client, "get", lambda *a, **kw: {"z": 1})
    client.course_summaries()
    client.list_lectures()
    client.course_stats("ml")
    assert len(store) >= 3
    client.invalidate_for_course("ml")
    assert len(store) == 0


# ----------------------------------------------------------------------- media

def test_media_url_maps_server_paths_to_backend():
    api = client.API
    assert client.media_url("data/processed/clips/3/clip_1.mp4") == (
        f"{api}/media/clips/3/clip_1.mp4"
    )
    assert client.media_url(r"data\processed\clips\3\clip_1.mp4") == (
        f"{api}/media/clips/3/clip_1.mp4"
    )


def test_media_url_rejects_bad_inputs():
    assert client.media_url("") is None
    assert client.media_url(None) is None
    assert client.media_url("data/processed/clips/notint/x.mp4") is None
    assert client.media_url("data/processed/clips/3/../escape.mp4") is None
    assert client.media_url("clip.mp4") is None  # no lecture id segment


def test_valid_course_id():
    assert client.valid_course_id("ml1")
    assert client.valid_course_id("a-b_c")
    assert not client.valid_course_id("")
    assert not client.valid_course_id("has space")
    assert not client.valid_course_id("x" * 300)


# --------------------------------------------------------- course-key normalize

def test_normalize_course_id():
    assert client.normalize_course_id(" ml 1 ") == "ML-1"
    assert client.normalize_course_id("ml1") == "ML1"
    assert client.normalize_course_id("ml  1") == "ML-1"
    assert client.normalize_course_id("a--b") == "A-B"
    assert client.normalize_course_id("a---b") == "A-B"
    assert client.normalize_course_id("") == ""
    assert client.normalize_course_id(None) == ""


def test_canonical_compare_is_case_insensitive():
    assert client.canonical_compare("ML1") == client.canonical_compare("ml1")
    assert client.canonical_compare("ml 1") == client.canonical_compare("ML-1")


def test_is_canonical_key():
    assert client.is_canonical_key("ML1")
    assert client.is_canonical_key("ML1-F23")
    assert not client.is_canonical_key("ml1")
    assert not client.is_canonical_key("ML_1")
    assert not client.is_canonical_key("")


# -------------------------------------------------------------- quota estimates

def test_whisper_requests_for():
    assert client.whisper_requests_for(0) == 0
    assert client.whisper_requests_for(0.0) == 0
    assert client.whisper_requests_for(299) == 1
    assert client.whisper_requests_for(300) == 1
    assert client.whisper_requests_for(301) == 2
    assert client.whisper_requests_for(900) == 3


def test_videos_left():
    assert client.videos_left(12, 900) == 4  # 3 req/lecture at 300s chunks
    assert client.videos_left(0, 900) == 0
    assert client.videos_left(5, 0) is None  # unknown duration


def test_usage_goes_through_cache_store(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(client, "_CACHE", client.CacheStore(clock=clock))
    calls = []

    def fake_get(path, params=None, timeout=30):
        calls.append(path)
        return {"services": {"groq.whisper": {"remaining_requests": 9}}}

    monkeypatch.setattr(client, "get", fake_get)
    assert client.usage()["services"]["groq.whisper"]["remaining_requests"] == 9
    assert client.usage()["services"]["groq.whisper"]["remaining_requests"] == 9
    assert calls == ["/usage"]  # 30s TTL: one HTTP call, memoized


# ------------------------------------------------------------ media streaming

def test_upload_media_streams_with_content_length(monkeypatch):
    captured = {}

    def fake_put(path, params=None, headers=None, data=None, timeout=600):
        captured.update(path=path, params=params, headers=headers, data=data)
        return {"id": 5, "status": "uploaded"}

    monkeypatch.setattr(client, "put", fake_put)
    payload = client.upload_media(
        5, "lec.mp4", b"x" * 3000, whisper_backend="groq", chunk_size=1024,
    )
    assert payload == {"id": 5, "status": "uploaded"}
    assert captured["path"] == "/lectures/5/media"
    assert captured["params"]["filename"] == "lec.mp4"
    assert captured["params"]["whisper_backend"] == "groq"
    assert captured["headers"]["Content-Length"] == "3000"
    chunks = list(captured["data"])
    assert b"".join(chunks) == b"x" * 3000
    assert len(chunks) == 3 and all(len(c) <= 1024 for c in chunks)


def test_upload_media_rejects_empty_bytes(monkeypatch):
    client.LAST_ERROR = None
    assert client.upload_media(1, "x.mp4", b"") is None
    assert client.take_last_error()["detail"] == "No media bytes to upload"


def test_upload_media_cancel_stops_the_stream(monkeypatch):
    import threading

    cancel = threading.Event()
    cancel.set()
    captured = {}

    def fake_put(path, params=None, headers=None, data=None, timeout=600):
        captured["data"] = data
        return {"id": 1}

    monkeypatch.setattr(client, "put", fake_put)
    client.upload_media(1, "x.mp4", b"abc" * 10, cancel=cancel)
    assert list(captured["data"]) == []  # nothing sent after cancel