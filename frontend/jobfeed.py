"""Client-side job feed — a push channel for job progress (Engine 2 / C4).

Why this exists: the progress monitor used to re-run the *entire* Streamlit
script every 0.5-1.5s to read a progress number. That rebuilt every element on
the page, which restarted every ``<video>`` player and made long lists unusable
while a job ran. Nothing in the framework can avoid a re-render on a push, so
the fix has two halves:

  1. this module keeps a live job snapshot in memory, fed by a **server-sent
     event** stream, so the value is already there when the UI asks and asking
     costs nothing;
  2. ``frontend.panels.shell`` renders the cards inside a ``st.fragment`` with
     ``run_every``, so only the card block re-executes. The rest of the page -
     the clip players, the graph, the quiz - stays mounted.

If the stream cannot be established (an older backend with no /jobs, a proxy
that buffers, an offline laptop) the feed falls back to polling ``GET /jobs``
and keeps retrying the stream with back-off. It never blocks the UI either way.
"""

import json
import threading
import time

from frontend import client

_POLL_INTERVAL_S = 1.0
_RECONNECT_BACKOFF_S = (1.0, 2.0, 5.0, 10.0)
_STREAM_INTERVAL_S = 1.0

# Connect / read timeouts for the stream. The read timeout must comfortably
# exceed the server's keep-alive interval, or an idle course would look dead.
_CONNECT_TIMEOUT_S = 5
_READ_TIMEOUT_S = 20.0


class JobFeed:
    """Background job-state snapshot, fed by SSE with a polling fallback.

    Thread-safe: written by the consumer thread, read by whichever Streamlit
    thread renders the fragment.
    """

    def __init__(self, api_base: str = None, course_id: str = None):
        self.api_base = (api_base or client.API).rstrip("/")
        self.course_id = course_id
        self._lock = threading.Lock()
        self._jobs = []
        self._mode = "starting"      # starting | stream | poll | unavailable
        self._stop = threading.Event()
        self._thread = None
        self._resp = None            # in-flight stream response (for stop())
        self._last_change = 0.0

    # ------------------------------------------------------------- lifecycle

    def start(self):
        """Start the consumer once; safe to call on every rerun."""
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="lecgap-job-feed", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        """Ask the consumer to finish, and unblock it if it is mid-read.

        A daemon thread parked on an idle socket would otherwise keep the
        connection - and its event loop - alive for the life of the process.
        """
        self._stop.set()
        with self._lock:
            resp, self._resp = self._resp, None
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001 - closing is best-effort
                pass

    # ----------------------------------------------------------------- reads

    def snapshot(self):
        """The most recent job list (a copy; callers cannot corrupt the feed)."""
        with self._lock:
            return [dict(j) for j in self._jobs]

    def job(self, job_id):
        """One job by id, or None when the feed has not seen it.

        The only read the UI performs per card; a None here is not an error -
        it means "no durable row for this job yet", and the caller decides
        whether to fall back to the legacy per-lecture endpoint.
        """
        if job_id is None:
            return None
        for row in self.snapshot():
            if row.get("id") == job_id:
                return row
        return None

    def mode(self) -> str:
        with self._lock:
            return self._mode

    def changed_since(self, token: float) -> bool:
        """Cheap change detection, so a fragment can no-op when nothing moved."""
        with self._lock:
            return self._last_change > token

    def change_token(self) -> float:
        with self._lock:
            return self._last_change

    # ---------------------------------------------------------------- writes

    def _publish(self, jobs, mode=None):
        with self._lock:
            self._jobs = list(jobs or [])
            if mode:
                self._mode = mode
            if self._jobs:
                self._last_change = time.time()

    # ----------------------------------------------------------------- loops

    def _run(self):
        attempt = 0
        while not self._stop.is_set():
            if self._stream_once():
                attempt = 0
                continue
            if self._stop.is_set():
                return
            # The stream is not available: take one cheap reading so the UI
            # still updates, then back off and try the stream again. (Polling
            # in a tight loop here would never retry the stream at all.)
            self._poll_once()
            attempt += 1
            delay = _RECONNECT_BACKOFF_S[
                min(attempt, len(_RECONNECT_BACKOFF_S) - 1)]
            if self._stop.wait(delay):
                return

    def _stream_once(self) -> bool:
        """One SSE connection. Returns False if it could not be established."""
        url = f"{self.api_base}/jobs/stream"
        params = {"interval_s": _STREAM_INTERVAL_S}
        if self.course_id:
            params["course_id"] = self.course_id
        try:
            resp = client.requests.get(
                url, params=params, headers=client._auth_headers(),
                stream=True, timeout=(_CONNECT_TIMEOUT_S, _READ_TIMEOUT_S),
            )
        except Exception:  # noqa: BLE001 - offline, refused, DNS, TLS...
            return False
        if resp.status_code != 200:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            return False
        with self._lock:
            self._resp = resp
        try:
            self._publish([], mode="stream")
            for raw in resp.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    return True
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "replace")
                if not raw or not raw.startswith("data: "):
                    continue          # 'retry:', ': keep-alive', 'event:'
                try:
                    self._publish(json.loads(raw[len("data: "):]), mode="stream")
                except ValueError:
                    continue          # a malformed frame must not kill the feed
            return True
        except Exception:  # noqa: BLE001 - dropped socket, read timeout...
            return False
        finally:
            with self._lock:
                if self._resp is resp:
                    self._resp = None
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

    def _poll_once(self) -> None:
        """One GET /jobs reading — the fallback while the stream is down."""
        jobs = client.get(
            "/jobs",
            params={"course_id": self.course_id} if self.course_id else None,
            timeout=5,
        )
        if isinstance(jobs, dict) and "jobs" in jobs:
            self._publish(jobs["jobs"], mode="poll")
        else:
            self._publish([], mode="unavailable")
        self._stop.wait(_POLL_INTERVAL_S)


_feed = None
_feed_guard = threading.Lock()


def job_feed(course_id: str = None) -> JobFeed:
    """Process-wide feed singleton (one SSE connection for all sessions).

    The stream is process-global, so ``course_id`` only shapes the *first*
    connection: later calls do not re-negotiate an already-open stream, they
    just share it. A single connection per process is the point - two browser
    sessions on one Streamlit server share the feed instead of doubling the
    backend's work.
    """
    global _feed
    with _feed_guard:
        if _feed is None:
            _feed = JobFeed(course_id=course_id).start()
        return _feed


def reset_feed_for_tests():
    global _feed
    with _feed_guard:
        if _feed is not None:
            _feed.stop()
        _feed = None
