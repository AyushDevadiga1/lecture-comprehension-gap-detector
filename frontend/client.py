"""Pure-Python LecGap API client + Tier-1 cache.

No Streamlit imports here — this module is the frontend<->backend boundary
defined by ``plan/FRONTEND_API_CONTRACT.md`` and is unit-testable without any
streamlit machinery.

Responsibilities:
  * validated base URL (LECGAP_API_URL; http/https + host only)
  * auth header (X-API-Key from LECGAP_API_KEY, when set)
  * error-safe get/post/delete that always extract the backend ``detail``
  * a TTL CacheStore (module singleton) shared by every session in the same
    process, with one explicit invalidation rule call sites use after mutations
  * ``media_url`` mapping server clip paths -> the Range-capable media endpoint

The apps are expected to import this module and call through it
(``client.get(...)`` etc.) so tests can replace ``client.requests`` or the
higher-level functions without touching the framework.
"""

import copy
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

_DEFAULT_API = "http://127.0.0.1:8000"
_API_KEY_ENV = "LECGAP_API_KEY"
_API_URL_ENV = "LECGAP_API_URL"

# One-shot structured record of the last failed request. The app renders a
# single top-level banner for kind == "auth" (401) and can surface other
# details for user-triggered loads. Cleared on success or via take_last_error().
LAST_ERROR = None

# Test seams (module-level so tests can neutralise retry sleeps).
RETRY_DELAY_S = 1.0
ENABLE_RETRY = True


def validated_api_url(raw: str = None) -> str:
    """Accept only http(s) URLs with a host (SECURITY_AUDIT #25)."""
    url = (raw if raw is not None else "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"{_API_URL_ENV} must be an http(s) URL with a host, got {raw!r}"
        )
    return url


API = validated_api_url(os.getenv(_API_URL_ENV, _DEFAULT_API))

_COURSE_ID_RE = r"^[\w\-]{1,128}$"


def _auth_headers() -> dict:
    key = os.getenv(_API_KEY_ENV, "")
    if key:
        return {"X-API-Key": key}
    return {}


def _record_error(kind, status, detail, path):
    global LAST_ERROR
    LAST_ERROR = {"kind": kind, "status": status, "detail": detail, "path": path}


def take_last_error():
    """Return and clear the recorded request error (used for the auth banner)."""
    global LAST_ERROR
    err, LAST_ERROR = LAST_ERROR, None
    return err


def _extract_detail(resp) -> str:
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])
    except Exception:  # noqa: BLE001 - non-JSON error body
        pass
    return resp.text


# ----------------------------------------------------------------- request core

def _request(method, path, *, timeout, headers=None, **kw):
    """Low-level transport with one retry on transient connection errors.

    Returns the (status_code, payload) tuple or raises an exception subclass of
    requests.RequestException / ValueError for JSON parsing. This is the only
    place that touches ``requests`` so tests need only replace
    ``client.requests``.
    """
    url = f"{API}{path}"
    hdr = _auth_headers()
    if headers:
        hdr.update(headers)
    try:
        r = requests.request(method, url, timeout=timeout, headers=hdr, **kw)
    except requests.Timeout as exc:
        _record_error("timeout", None, f"Request to {path} timed out after {timeout}s.", path)
        raise
    except requests.RequestException as exc:
        _record_error("network", None, f"Backend request failed ({exc.__class__.__name__}): {exc}", path)
        if ENABLE_RETRY and isinstance(exc, requests.ConnectionError):
            time.sleep(RETRY_DELAY_S)
            try:
                r = requests.request(method, url, timeout=timeout, headers=hdr, **kw)
            except requests.RequestException as second:
                _record_error("network", None, f"Backend request failed ({second.__class__.__name__}): {second}", path)
                raise
        else:
            raise
    if r.status_code >= 400:
        _record_error("http", r.status_code, _extract_detail(r), path)
        return r.status_code, None
    try:
        payload = r.json()
    except Exception as exc:  # noqa: BLE001 - JSON shape errors surface neatly
        _record_error("json", r.status_code, f"Could not read {path}: {exc}", path)
        return r.status_code, None
    global LAST_ERROR
    LAST_ERROR = None
    return r.status_code, payload


def get(path, params=None, timeout: int = 30):
    """Live GET (never cached) — progress polling and anything time-sensitive."""
    try:
        return _request("GET", path, timeout=timeout, params=params)[1]
    except requests.RequestException:
        return None


def post(path, json=None, files=None, data=None, params=None, timeout: int = 600):
    """POST; network failures and 4xx/5xx return None (``LAST_ERROR`` holds detail)."""
    try:
        return _request(
            "POST", path, timeout=timeout, json=json, files=files, data=data, params=params
        )[1]
    except requests.RequestException:
        return None


def delete(path, timeout: int = 30):
    try:
        return _request("DELETE", path, timeout=timeout)[1]
    except requests.RequestException:
        return None


def put(path, params=None, headers=None, data=None, timeout: int = 600):
    try:
        return _request("PUT", path, timeout=timeout, params=params,
                        headers=headers, data=data)[1]
    except requests.RequestException:
        return None


# ----------------------------------------------------------------- Tier-1 cache

class CacheStore:
    """TTL keyed store. Values are returned as copies so callers can never
    poison the cache by mutating a payload. Calls and clocks are injectable for
    deterministic tests."""

    __slots__ = ("_clock", "_lock", "_store")

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._store = {}  # key -> (as_of, value)

    def _key(self, method, path, params):
        parts = []
        if params:
            for k in sorted(params):
                parts.append(f"{k}={params[k]}")
        return method + " " + path + ("?" + "&".join(parts) if parts else "")

    def get(self, method, path, params=None, ttl=60.0, loader=None):
        key = self._key(method, path, params)
        now = self._clock()
        with self._lock:
            hit = self._store.get(key)
            if hit is not None and now - hit[0] <= ttl:
                return copy.deepcopy(hit[1])
        if loader is None:
            return None
        value = loader()
        if value is None:
            return None  # never cache failures
        with self._lock:
            self._store[key] = (now, copy.deepcopy(value))
        return copy.deepcopy(value)

    def invalidate(self, prefix):
        with self._lock:
            stale = [k for k in self._store if k.startswith(prefix)]
            for k in stale:
                del self._store[k]

    def invalidate_all(self):
        with self._lock:
            self._store.clear()

    def __len__(self):
        with self._lock:
            return len(self._store)


_CACHE = CacheStore()


def invalidate(prefix):
    """Drop cached entries whose key starts with ``prefix`` (method-prefixed)."""
    for m in ("GET", "POST", "DELETE"):
        _CACHE.invalidate(f"{m} {prefix}")


def invalidate_all():
    _CACHE.invalidate_all()


def invalidate_for_course(course_id):
    """The ONE invalidation rule call sites use after any mutation that can
    change a course or lecture: clears course/lecture lists and the course's
    scoped keys. Everything course-relevant lives under /courses or /lectures,
    so both namespaces are cleared (the data is small and safe)."""
    invalidate("/courses")
    invalidate("/lectures")


# ----------------------------------------------------------------- cached reads

def _cached(path, params=None, ttl=60.0):
    return _CACHE.get("GET", path, params, ttl, loader=lambda: get(path, params=params))


def course_summaries(ttl: float = 60.0):
    """GET /courses — memoized course summaries."""
    return _cached("/courses", ttl=ttl)


def list_lectures(ttl: float = 60.0):
    """GET /lectures — memoized lecture list."""
    return _cached("/lectures", ttl=ttl)


def lecture_detail(lecture_id: int, ttl: float = 300.0):
    """GET /lectures/{id} — segments + concepts for the timeline."""
    return _cached(f"/lectures/{int(lecture_id)}", ttl=ttl)


def lecture_clips(lecture_id: int, ttl: float = 60.0):
    """GET /lectures/{id}/clips — clip batch."""
    return _cached(f"/lectures/{int(lecture_id)}/clips", ttl=ttl)


def course_stats(course_id: str, ttl: float = 300.0):
    """GET /courses/{id}/stats — faculty heatmap + divergence."""
    return _cached(f"/courses/{course_id}/stats", ttl=ttl)


def course_graph(course_id: str, ttl: float = 300.0):
    """GET /courses/{id}/graph — course DAG payload."""
    return _cached(f"/courses/{course_id}/graph", ttl=ttl)


def course_snapshot(course_id: str, ttl: float = 5.0):
    """GET /courses/{id}/snapshot — derived per-course readiness (plan §13).

    Short TTL by design: it is the live consistency layer both dashboards poll
    (~5s), so a change made in one session/dashboard surfaces in the other."""
    return _cached(f"/courses/{course_id}/snapshot", ttl=ttl)


def usage(ttl: float = 30.0):
    """GET /usage — live per-service Groq quota + local/ollama availability."""
    return _cached("/usage", ttl=ttl)


# ------------------------------------------------------------- course keywords

_COURSE_SLUG_RE = r"^[A-Z][A-Z0-9-]{0,127}$"


def normalize_course_id(key) -> str:
    """Canonical course KEY — ``strip → upper → whitespace→'-' → collapse repeats``
    applied to a new course identifier, so the same course never fragments into
    'ML1' vs 'ml1' vs 'ml 1'. Existing keys (any case) are left untouched and
    still accepted by ``valid_course_id`` for read/compare paths."""
    text = (key or "").strip().upper()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text


def canonical_compare(key: str) -> str:
    """Case-insensitive identity used for duplicate detection (never sent)."""
    return (key or "").strip().lower().replace(" ", "-")


# ----------------------------------------------------------------- media

def media_url(path):
    """Map a server clip path to the Range-capable media endpoint URL.

    Payloads (v1 contract) carry filesystem paths like
    ``data/processed/clips/3/clip_name.mp4``; the browser can't fetch those, so
    the frontend maps them to an absolute backend URL. The lecture id is read
    from the path itself (second-to-last segment). Returns None for an
    empty/bogus path or a non-int lecture id.
    """
    if not path:
        return None
    normalised = str(path).replace("\\", "/")
    parts = [p for p in normalised.split("/") if p]
    if len(parts) < 2 or ".." in parts or "." in parts:
        return None
    filename = parts[-1]
    lecture_id = parts[-2]
    if not filename:
        return None
    try:
        lecture_id = int(lecture_id)
    except (TypeError, ValueError):
        return None
    return f"{API}/media/clips/{lecture_id}/{filename}"


def upload_media(lecture_id, filename, file_bytes, whisper_backend=None,
                 *, chunk_size: int = 1024 * 1024, cancel=None):
    """Stream one lecture's media to PUT /lectures/{id}/media (two-step upload).

    The request body is generated lazily in ``chunk_size`` slices and sent with
    an explicit Content-Length, so requests streams from memory without
    building another full copy; the backend publishes ``uploading`` progress on
    the lecture's progress row. Passing ``cancel`` (a threading.Event) stops
    the generator between chunks.

    Returns the LectureOut payload (truthy) or None (LAST_ERROR holds detail).
    """
    if not file_bytes:
        _record_error("http", 400, "No media bytes to upload", "/media")
        return None
    size = len(file_bytes)

    params = {"filename": filename}
    if whisper_backend:
        params["whisper_backend"] = whisper_backend

    def _chunks():
        sent = 0
        while sent < size:
            if cancel is not None and cancel.is_set():
                return
            end = min(sent + chunk_size, size)
            yield file_bytes[sent:end]
            sent = end

    return put(
        f"/lectures/{int(lecture_id)}/media",
        params=params,
        headers={
            "Content-Length": str(size),
            "Content-Type": "application/octet-stream",
        },
        data=_chunks(),
        timeout=600,
    )


def valid_course_id(course_id) -> bool:
    """Accepts the backend's pattern (letters/digits/underscore/hyphen, 1-128
    chars) so existing keys in any case stay usable; new course keys are also
    checked against the canonical uppercase slug via ``is_canonical_key``."""
    return bool(re.match(_COURSE_ID_RE, course_id or ""))


def is_canonical_key(course_id) -> bool:
    return bool(re.match(_COURSE_SLUG_RE, course_id or ""))


# ------------------------------------------------------------- quota estimates

def whisper_requests_for(duration_s, max_chunk_s: int = 300) -> int:
    """Groq Whisper requests for one lecture of ``duration_s`` seconds
    (one chunk per window; mirrors transcribe._split_flac up to the cap)."""
    duration = float(duration_s or 0)
    if duration <= 0:
        return 0
    from math import ceil

    return max(1, ceil(duration / max(max_chunk_s, 1)))


def videos_left(remaining_requests, duration_s, max_chunk_s: int = 300):
    """Rough 'how many more lectures fit' given the current upload's length."""
    per = whisper_requests_for(duration_s, max_chunk_s)
    return None if not per else int(remaining_requests // per)