"""C4 regression tests — the SSE-driven progress cards.

The complaint C4 exists for: a background job re-rendered the whole dashboard
every 0.5-1.5s, so every ``<video>`` player restarted and long lists were
unusable while a job ran. The fix has two halves, and each is pinned here:

  * progress arrives by push (``frontend.jobfeed``), so a card renders from an
    in-memory snapshot and fetches nothing for a job the registry knows about;
  * the cards live in a ``st.fragment(run_every=...)``, so a completion is
    *recorded* rather than announced in place - otherwise the "Done" line and a
    panel's follow-up would be rebuilt and dropped every second.

``tests/test_c0_fixes.py`` still pins the C0 termination rules (stall cutoffs,
the upload-thread states, the 6h backstop); these tests pin how the same job is
*read* once the durable registry answers for it.
"""

import types

import pytest

from frontend import client as client_mod
from frontend import state
from frontend.panels import shell


# --------------------------------------------------------------- fixtures

class _SessionState(dict):
    """The dict-shaped session state ``frontend.state`` expects."""


@pytest.fixture
def sess(monkeypatch):
    ss = _SessionState()
    monkeypatch.setattr(state, "st", types.SimpleNamespace(session_state=ss))
    return ss


class _St:
    def __init__(self):
        self.bars = []
        self.captions = []
        self.warnings = []
        self.errors = []
        self.successes = []
        self.buttons = {}

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


@pytest.fixture
def fake_st(monkeypatch):
    st = _St()
    monkeypatch.setattr(shell, "st", st)
    return st


class _Feed:
    """A stand-in for the SSE feed: a snapshot, read by id."""

    def __init__(self, jobs=()):
        self._jobs = [dict(j) for j in jobs]

    def snapshot(self):
        return [dict(j) for j in self._jobs]

    def job(self, job_id):
        if job_id is None:
            return None
        for row in self._jobs:
            if row.get("id") == job_id:
                return dict(row)
        return None

    def mode(self):
        return "stream"


def _remote(**kw):
    row = {"id": 5, "kind": "extract", "status": "running", "stage": "extracting",
           "detail": "Reading the lecture", "progress_pct": 20,
           "duration_s": 12, "terminal": False}
    row.update(kw)
    return row


@pytest.fixture
def no_http(monkeypatch):
    """Fail loudly if a card reaches for the network instead of the feed."""
    def _get(path, params=None, timeout=30):
        raise AssertionError(f"unexpected HTTP GET {path}")

    monkeypatch.setattr(client_mod, "get", _get)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)


# ----------------------------------------------------------- reading a job

def test_a_known_job_is_rendered_from_the_feed_without_fetching(sess, fake_st,
                                                                no_http):
    shell.start_job("ml", 3, "Concept extraction", kind="extract", job_id=5)
    keep = shell.render_job_cards(state.get("jobs", "items"),
                                  feed=_Feed([_remote()]))

    assert [j["job_id"] for j in keep] == [5]
    assert fake_st.bars[0][0][0] == 20, "the bar must show the durable pct"
    assert any("Reading the lecture" in c for c in fake_st.captions)
    assert any("elapsed" in c for c in fake_st.captions)
    assert not fake_st.errors


def test_a_job_without_a_durable_row_falls_back_to_the_lecture_endpoint(monkeypatch,
                                                                        sess, fake_st):
    """The window between "the POST returned" and "the stream connected"."""
    calls = []

    def _get(path, params=None, timeout=30):
        calls.append(path)
        return {"status": "extracting", "stage": "extracting",
                "progress_pct": 55, "detail": "legacy"}

    monkeypatch.setattr(client_mod, "get", _get)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    shell.start_job("ml", 3, "Concept extraction", kind="extract")
    keep = shell.render_job_cards(state.get("jobs", "items"), feed=_Feed([]))

    assert calls == ["/lectures/3/progress"]
    assert len(keep) == 1
    assert fake_st.bars[0][0][0] == 55


def test_the_feed_is_not_opened_for_jobs_with_nothing_to_look_up(monkeypatch, sess,
                                                                  fake_st):
    """A job with no id has no durable row, so no connection is opened for it."""
    from frontend import jobfeed

    monkeypatch.setattr(client_mod, "get",
                        lambda *a, **k: {"status": "extracting",
                                         "stage": "extracting",
                                         "progress_pct": 1})
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    opened = []
    monkeypatch.setattr(jobfeed, "job_feed",
                        lambda course_id=None: opened.append(course_id))

    shell.start_job("ml", 3, "Concept extraction", kind="extract")
    shell.render_job_cards(state.get("jobs", "items"))
    assert opened == [], "no durable id -> no feed, the legacy endpoint answers"


# ---------------------------------------------------------- terminal states

def test_a_finished_job_is_recorded_not_announced(sess, fake_st, no_http):
    """A fragment re-renders every second; a success line in it would flash."""
    shell.start_job("ml", 3, "Concept extraction", kind="extract", job_id=5,
                    after="clips_list")
    keep = shell.render_job_cards(state.get("jobs", "items"),
                                  feed=_Feed([_remote(status="ready",
                                                      progress_pct=100,
                                                      terminal=True)]))

    assert keep == [], "a finished job is dropped from the live list"
    assert fake_st.successes == [], "the announcement belongs to the page body"
    pending = state.get("jobs", "completed")
    assert [p["lecture_id"] for p in pending] == [3]
    assert pending[0]["after"] == "clips_list"


def test_drain_ready_announces_once_and_fires_the_follow_up(sess, fake_st):
    shell.start_job("ml", 3, "Clip cutting", kind="clips", after="clips_list",
                    job_id=5)
    shell.render_job_cards(state.get("jobs", "items"),
                           feed=_Feed([_remote(status="ready", progress_pct=100,
                                               terminal=True)]))

    seen = []
    shell.drain_ready(on_ready=lambda job, lid: seen.append((job.get("after"), lid)))
    assert fake_st.successes, "the finished job is announced on the page"
    assert seen == [("clips_list", 3)]

    shell.drain_ready(on_ready=lambda job, lid: seen.append("again"))
    assert len(seen) == 1, "a completion must be announced exactly once"
    assert len(fake_st.successes) == 1


def test_drain_ready_with_nothing_pending_is_silent(sess, fake_st):
    shell.drain_ready()
    assert fake_st.successes == []


@pytest.mark.parametrize("status,expected", [
    ("error", "quiz generation failed"),
    ("orphaned", "server restart"),
    ("cancelled", "cancelled"),
    ("not_found", "no such job"),
])
def test_a_dead_job_reports_why_and_leaves(sess, fake_st, no_http, status, expected):
    detail = {"error": "quiz generation failed",
              "orphaned": None,
              "cancelled": None,
              "not_found": "no such job"}[status]
    shell.start_job("ml", 3, "Quiz", kind="extract", job_id=5)
    keep = shell.render_job_cards(state.get("jobs", "items"),
                                  feed=_Feed([_remote(status=status,
                                                      terminal=True,
                                                      detail=detail)]))
    assert keep == []
    assert expected in fake_st.errors[0]


def test_an_unreachable_job_is_retried_then_reported(sess, fake_st, monkeypatch):
    monkeypatch.setattr(client_mod, "get", lambda *a, **k: None)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    shell.start_job("ml", 3, "Concept extraction", kind="extract")

    for _ in range(shell._MAX_POLL_FAILS - 1):
        assert len(shell.render_job_cards(state.get("jobs", "items"),
                                          feed=_Feed([]))) == 1
    assert shell.render_job_cards(state.get("jobs", "items"),
                                  feed=_Feed([])) == []
    assert "unreachable" in fake_st.warnings[0]


# --------------------------------------------------------- the upload hand-off

def test_an_upload_card_becomes_the_job_the_put_enqueued(monkeypatch, sess, fake_st,
                                                        no_http):
    """The transfer is client-side; the PUT is what returns a durable job."""
    monkeypatch.setattr(shell, "_upload_status",
                        lambda lid, kind: ("done", True, None, 91))
    shell.start_job("ml", 3, "Upload + transcribe", kind="upload")

    keep = shell.render_job_cards(state.get("jobs", "items"), feed=_Feed([]))
    assert len(keep) == 1
    assert keep[0]["kind"] == "transcribe"
    assert keep[0]["job_id"] == 91, "the card must follow the real job"
    assert not fake_st.errors


def test_a_failed_upload_is_reported_and_dropped(monkeypatch, sess, fake_st, no_http):
    monkeypatch.setattr(shell, "_upload_status",
                        lambda lid, kind: ("done", False, "Upload failed.", None))
    shell.start_job("ml", 3, "Upload + transcribe", kind="upload")
    assert shell.render_job_cards(state.get("jobs", "items"), feed=_Feed([])) == []
    assert fake_st.errors == ["Upload failed."]


def test_an_upload_in_flight_shows_its_own_percentage(monkeypatch, sess, fake_st):
    monkeypatch.setattr(shell, "_upload_status",
                        lambda lid, kind: ("pending", False, None, None))
    monkeypatch.setattr(client_mod, "get", lambda *a, **k: {
        "status": "uploaded", "stage": "uploading", "progress_pct": 42,
        "detail": "Uploading: 42%"})
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    shell.start_job("ml", 3, "Upload + transcribe", kind="upload")

    keep = shell.render_job_cards(state.get("jobs", "items"), feed=_Feed([]))
    assert len(keep) == 1
    assert fake_st.bars[0][0][0] == 42
    assert fake_st.bars[0][1]["text"] == "Uploading: 42%"


# ------------------------------------------------------------ the fragment

def test_the_fragment_keeps_the_other_monitors_jobs(sess, fake_st, monkeypatch):
    """Two monitors, one page: each writes back only its own verdict."""
    monkeypatch.setattr(client_mod, "get", lambda *a, **k: {
        "status": "extracting", "stage": "extracting", "progress_pct": 10})
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    shell.start_job("ml", 3, "Concept extraction", kind="extract", job_id=5)
    shell.start_job("ml", 4, "Clip cutting", kind="clips", job_id=6)

    feed = _Feed([_remote(), _remote(id=6, kind="clips", stage="clips")])
    shell.render_progress_cards(kinds=("extract", "graph", "clips"), feed=feed)
    kinds = sorted(j["kind"] for j in state.get("jobs", "items"))
    assert kinds == ["clips", "extract"], "both jobs survive one monitor's pass"

    shell.render_progress_cards(kinds=("upload", "transcribe"), feed=feed)
    assert len(state.get("jobs", "items")) == 2, "a second monitor must not drop them"


def test_a_monitor_with_no_jobs_of_its_kind_does_nothing(sess, fake_st):
    shell.start_job("ml", 3, "Concept extraction", kind="extract", job_id=5)
    shell.render_progress_cards(kinds=("upload", "transcribe"),
                                feed=_Feed([_remote()]))
    assert [j["kind"] for j in state.get("jobs", "items")] == ["extract"]
    assert fake_st.bars == []


# ------------------------------------------------ the form -> card hand-off

class _Upload:
    def __init__(self, name, payload):
        self.name = name
        self._payload = payload

    def getvalue(self):
        return self._payload


class _FormSt(_St):
    """Just enough Streamlit for the upload form, with the form submitted."""

    def __init__(self):
        super().__init__()
        self.upload = _Upload("lec.mp4", b"x" * 20)

    def form(self, *_a, **_k):
        import contextlib

        return contextlib.nullcontext()

    def selectbox(self, _label, options, **_k):
        return options[0]

    def file_uploader(self, *_a, **_k):
        return self.upload

    def form_submit_button(self, *_a, **_k):
        return True

    def checkbox(self, *_a, **_k):
        return True


def test_the_form_streams_the_media_and_the_card_follows_the_queued_job(
        monkeypatch, sess):
    """The whole upload hand-off, panel to card.

    The row is created with a form POST (fast, no bytes), the media is streamed
    in a background thread, and the card the form registered becomes the card
    of the transcription job the PUT enqueued.
    """
    from frontend.panels import ingest

    form_st = _FormSt()
    monkeypatch.setattr(ingest, "st", form_st)
    monkeypatch.setattr(shell, "st", form_st)

    calls = []

    def post(path, **kw):
        calls.append(("create", kw))
        return {"id": 77, "status": "uploaded"}

    def upload_media(lecture_id, filename, payload, **kw):
        calls.append(("upload", {"lecture_id": lecture_id,
                                 "filename": filename, "bytes": len(payload)}))
        return {"id": 77, "status": "uploaded", "job_id": 5}

    monkeypatch.setattr(client_mod, "post", post)
    monkeypatch.setattr(client_mod, "upload_media", upload_media)
    monkeypatch.setattr(client_mod, "list_lectures", lambda ttl=60.0: [])
    monkeypatch.setattr(client_mod, "invalidate_all", lambda: None)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)

    ingest.render_ingest_form("ml1")

    assert [c[0] for c in calls] == ["create", "upload"]
    assert "files" not in calls[0][1], "the POST must not carry the media"
    assert calls[0][1]["data"]["course_id"] == "ml1"
    assert any("Uploading lecture #77" in s for s in form_st.successes)

    with shell._UPLOADS_LOCK:
        entry = shell._UPLOADS.get(77)
    if entry is not None:   # the card has not consumed the transfer yet
        assert entry["done"].wait(5)

    keep = shell.render_job_cards(state.get("jobs", "items"),
                                  feed=_Feed([_remote(id=5, kind="transcribe")]))
    assert len(keep) == 1
    assert keep[0]["kind"] == "transcribe" and keep[0]["job_id"] == 5
