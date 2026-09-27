"""Job-feed unit tests (Engine 2 / C4) — ``frontend/jobfeed.py``.

The feed is the frontend's push channel: one SSE connection per process that
keeps the job snapshot in memory, so the progress cards can render without
fetching anything and without re-running the page. These tests drive the loops
directly with fake sockets - no Streamlit, no network, no threads except the one
asserting that ``stop()`` actually unblocks a reader.
"""

import json
import threading
import time

import pytest

from frontend import client as client_mod
from frontend import jobfeed


# ------------------------------------------------------------------- fakes

class _FakeResponse:
    """A stand-in for a streamed ``requests`` response."""

    def __init__(self, lines=(), status_code=200, block_after=None):
        self.status_code = status_code
        self._lines = list(lines)
        self.closed = False
        self._block_after = block_after

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            yield line
        if self._block_after is not None:
            # a real idle stream parks here; the test releases it from another
            # thread to prove that stop() closes the socket out from under it
            self._block_after.wait(5)

    def close(self):
        self.closed = True
        if self._block_after is not None:
            # a real close makes the parked read fail/return at once
            self._block_after.set()
            self._block_after = None


def _frame(jobs):
    """One SSE event, as the wire actually carries it (three lines)."""
    return "event: jobs\ndata: " + json.dumps(jobs) + "\n\n"


def _sse_feed(monkeypatch, body, status_code=200, block_after=None):
    """A JobFeed whose stream replays `body`, then parks on the socket.

    ``body`` is either a raw SSE blob (split into lines the way requests would)
    or an explicit list of already-split lines - which is how a ``bytes`` frame
    is simulated.
    """
    lines = body.splitlines() if isinstance(body, str) else list(body)
    resp = _FakeResponse(lines, status_code=status_code,
                         block_after=block_after)
    seen = {}

    def _get(url, params=None, headers=None, stream=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        seen["timeout"] = timeout
        return resp

    monkeypatch.setattr(client_mod.requests, "get", _get)
    return resp, seen


# --------------------------------------------------------------- stream path

def test_stream_frames_publish_the_snapshot(monkeypatch):
    jobs = [{"id": 5, "kind": "transcribe", "status": "running", "stage": "transcribing",
             "progress_pct": 40, "terminal": False}]
    body = "retry: 2000\n\n: keep-alive\n\n" + _frame(jobs) + ": keep-alive\n\n"
    resp, seen = _sse_feed(monkeypatch, body)

    feed = jobfeed.JobFeed(api_base="http://api:8000")
    assert feed._stream_once() is True

    assert feed.mode() == "stream"
    assert feed.snapshot() == jobs
    assert seen["url"] == "http://api:8000/jobs/stream"
    assert seen["params"]["interval_s"] == jobfeed._STREAM_INTERVAL_S
    assert resp.closed, "the response must be closed when the stream ends"


def test_stream_request_carries_the_api_key(monkeypatch):
    monkeypatch.setenv("LECGAP_API_KEY", "s3cret")
    _resp, seen = _sse_feed(monkeypatch, _frame([]))
    jobfeed.JobFeed(api_base="http://api:8000")._stream_once()
    assert seen["headers"] == {"X-API-Key": "s3cret"}


def test_bytes_frames_are_decoded(monkeypatch):
    """requests only decodes for us when the response declares an encoding."""
    jobs = [{"id": 9, "status": "ready", "terminal": True}]
    _sse_feed(monkeypatch, [b"data: " + json.dumps(jobs).encode(), b"", b""])

    feed = jobfeed.JobFeed(api_base="http://api:8000")
    feed._stream_once()
    assert feed.snapshot() == jobs


def test_a_malformed_frame_does_not_kill_the_feed(monkeypatch):
    jobs = [{"id": 1, "status": "running"}]
    _sse_feed(monkeypatch, "data: {not json\n\n" + _frame(jobs))

    feed = jobfeed.JobFeed(api_base="http://api:8000")
    assert feed._stream_once() is True
    assert feed.snapshot() == jobs, "a bad frame must be skipped, not fatal"


def test_a_404_stream_is_not_a_stream(monkeypatch):
    """An older backend answers the poll endpoint and 404s the stream."""
    _sse_feed(monkeypatch, [], status_code=404)
    assert jobfeed.JobFeed(api_base="http://api:8000")._stream_once() is False


def test_a_dead_socket_is_not_a_stream(monkeypatch):
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(client_mod.requests, "get", _boom)
    assert jobfeed.JobFeed(api_base="http://api:8000")._stream_once() is False


# ---------------------------------------------------------------- reads

def test_snapshot_is_a_copy(monkeypatch):
    jobs = [{"id": 3, "status": "running"}]
    _sse_feed(monkeypatch, _frame(jobs))
    feed = jobfeed.JobFeed(api_base="http://api:8000")
    feed._stream_once()

    snap = feed.snapshot()
    snap[0]["status"] = "tampered"
    assert feed.snapshot()[0]["status"] == "running"
    assert feed.job(3)["status"] == "running"
    assert feed.job(4) is None
    assert feed.job(None) is None


def test_change_token_only_moves_when_there_is_something_to_show(monkeypatch):
    _sse_feed(monkeypatch, ["retry: 2000", _frame([])])
    feed = jobfeed.JobFeed(api_base="http://api:8000")
    before = feed.change_token()
    feed._stream_once()
    assert feed.change_token() == before, "an empty snapshot is not a change"
    assert feed.changed_since(before) is False


# -------------------------------------------------------------- poll path

def test_poll_fallback_reads_the_job_list(monkeypatch):
    jobs = [{"id": 7, "status": "running", "progress_pct": 5}]
    monkeypatch.setattr(client_mod, "get", lambda *a, **k: {"jobs": jobs})
    feed = jobfeed.JobFeed(api_base="http://api:8000", course_id="ml")
    feed._stop.set()          # return from the inter-poll wait immediately
    feed._poll_once()
    assert feed.snapshot() == jobs
    assert feed.mode() == "poll"


def test_poll_fallback_reports_unavailable(monkeypatch):
    monkeypatch.setattr(client_mod, "get", lambda *a, **k: None)
    feed = jobfeed.JobFeed(api_base="http://api:8000")
    feed._stop.set()
    feed._poll_once()
    assert feed.mode() == "unavailable"
    assert feed.snapshot() == []


def test_the_stream_is_retried_instead_of_polling_forever(monkeypatch):
    """The fallback must not become a dead end.

    Polling in a tight loop after the first stream failure would look like a
    working feed while the stream was never reopened - a proxy restart or a
    backend restart would leave the UI on polling forever.
    """
    monkeypatch.setattr(jobfeed, "_RECONNECT_BACKOFF_S", (0.0, 0.0))
    monkeypatch.setattr(jobfeed, "_POLL_INTERVAL_S", 0.0)

    attempts = {"stream": 0, "poll": 0}

    class _Feed(jobfeed.JobFeed):
        def _stream_once(self):
            attempts["stream"] += 1
            return attempts["stream"] >= 3      # fails twice, then succeeds

        def _poll_once(self):
            attempts["poll"] += 1
            self._publish([], mode="poll")

    feed = _Feed(api_base="http://api:8000")
    feed._stop.wait(0.0)
    thread = threading.Thread(target=feed._run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while attempts["stream"] < 3 and time.time() < deadline:
        time.sleep(0.01)
    feed.stop()
    thread.join(timeout=5)

    assert attempts["stream"] >= 3, "the stream must be re-attempted after a failure"
    assert attempts["poll"] >= 2, "each failed attempt still takes one reading"


# --------------------------------------------------------------- lifecycle

def test_stop_closes_an_idle_stream(monkeypatch):
    """A daemon thread parked on an idle socket must not outlive the app."""
    parked = threading.Event()
    body = _frame([{"id": 1, "status": "running"}])
    monkeypatch.setattr(client_mod.requests, "get",
                        lambda *a, **k: _FakeResponse(body.splitlines(),
                                                      block_after=parked))
    feed = jobfeed.JobFeed(api_base="http://api:8000")
    thread = threading.Thread(target=feed._run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not feed.snapshot() and time.time() < deadline:
        time.sleep(0.01)
    assert feed.snapshot(), "the first frame must land before we stop"

    feed.stop()
    thread.join(timeout=5)
    assert not thread.is_alive(), "stop() must unblock the consumer"


def test_start_is_idempotent(monkeypatch):
    monkeypatch.setattr(client_mod.requests, "get",
                        lambda *a, **k: _FakeResponse([]))
    feed = jobfeed.JobFeed(api_base="http://api:8000")
    first = feed.start()
    second = feed.start()
    assert first is second
    assert feed._thread is not None
    feed.stop()


def test_singleton_is_shared_by_every_session(monkeypatch):
    monkeypatch.setattr(jobfeed.JobFeed, "start", lambda self: self)
    jobfeed.reset_feed_for_tests()
    one = jobfeed.job_feed(course_id="ml")
    two = jobfeed.job_feed(course_id="cv")
    assert one is two, "one connection per process, however many sessions"
    assert one.course_id == "ml", "a later call must not re-negotiate the stream"


def test_reset_drops_the_singleton():
    jobfeed.reset_feed_for_tests()
    assert jobfeed._feed is None


@pytest.mark.parametrize("mode", ["stream", "poll", "unavailable"])
def test_modes_are_reported_verbatim(mode):
    feed = jobfeed.JobFeed(api_base="http://api:8000")
    feed._publish([], mode=mode)
    assert feed.mode() == mode
