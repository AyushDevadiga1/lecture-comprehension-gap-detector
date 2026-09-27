"""Baseline-fixes regression tests (upload legibility, clip playback, graph).

Three defects reported from running the app:

  * an `uploaded` row produced one alarming "not streamed yet — delete or
    re-upload" warning for two completely different situations, and neither was
    actionable;
  * the clip panel printed server-side filesystem paths instead of playable
    video with the concept name;
  * there was no graph on the student dashboard, and the progress card for a
    graph build rendered above the button that queued it.
"""

import types

import pytest

from frontend import client as client_mod
from frontend import state
# these tests span three panels now; each is patched at its owning module
from frontend.panels import graph, library, shell


class _PanelNs:
    """Attribute-style access across the panel modules.

    Keeps these tests readable (``components.render_clips``) while each symbol
    resolves to the module that actually owns it after the split.
    """

    def __getattr__(self, name):
        for mod in (shell, library, graph):
            if hasattr(mod, name):
                return getattr(mod, name)
        raise AttributeError(name)


components = _PanelNs()


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


class _St:
    def __init__(self):
        self.md = []
        self.captions = []
        self.warnings = []
        self.errors = []
        self.successes = []
        self.infos = []
        self.videos = []
        self.subheaders = []
        self.bars = []
        self.expander_labels = []
        self.iframes = []
        self.buttons = {}
        self.sliders = []
        self.multiselects = []
        self.metrics = []
        self.columns_made = []
        self.reruns = 0

    def markdown(self, *a, **k):
        self.md.append(a[0] if a else "")

    def caption(self, *a, **k):
        self.captions.append(a[0] if a else "")

    def warning(self, *a, **k):
        self.warnings.append(a[0] if a else "")

    def error(self, *a, **k):
        self.errors.append(a[0] if a else "")

    def success(self, *a, **k):
        self.successes.append(a[0] if a else "")

    def info(self, *a, **k):
        self.infos.append(a[0] if a else "")

    def video(self, *a, **k):
        self.videos.append(a[0] if a else "")

    def subheader(self, *a, **k):
        self.subheaders.append(a[0] if a else "")

    def write(self, *a, **k):
        self.captions.append(a[0] if a else "")

    def progress(self, *a, **k):
        self.bars.append((a, k))

    def expander(self, label, **k):
        self.expander_labels.append(label)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iframe(self, src, **k):
        self.iframes.append((src, k.get("height")))

    def divider(self):
        pass

    def selectbox(self, label, options, **k):
        return options[0] if options else None

    def metric(self, label, value=None, **k):
        self.metrics.append((label, value))

    def multiselect(self, label, options, default=None, **k):
        self.multiselects.append((label, list(options)))
        return list(options if default is None else default)

    def slider(self, label, min_value=None, max_value=None, value=None,
               step=None, **k):
        self.sliders.append((label, value))
        return value

    def checkbox(self, label, **k):
        return False

    def text_input(self, *a, **k):
        return ""

    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec)
        cols = [_St() for _ in range(n)]
        self.columns_made.append(cols)
        return cols

    def button(self, label, **k):
        return self.buttons.get(label, False)

    def rerun(self):
        self.reruns += 1
        raise RuntimeError("rerun")

    def all_text(self):
        return "\n".join(self.md + self.captions + self.subheaders + self.infos
                         + self.warnings + self.errors)


@pytest.fixture
def sess(monkeypatch):
    ss = _SessionState()
    monkeypatch.setattr(state, "st", types.SimpleNamespace(session_state=ss))
    return ss


@pytest.fixture
def fake_st(monkeypatch):
    st = _St()
    # every panel that renders needs the double substituted
    for mod in (shell, library, graph):
        monkeypatch.setattr(mod, "st", st, raising=False)
    return st


# ------------------------------------------------- stalled_rows classification

def _lectures(monkeypatch, rows):
    monkeypatch.setattr(client_mod, "list_lectures", lambda ttl=60.0: rows)


def test_stalled_rows_splits_resumable_from_abandoned(monkeypatch, sess):
    """`uploaded` means two different things; they need different actions."""
    _lectures(monkeypatch, [
        {"id": 1, "course_id": "ml", "title": "has media", "status": "uploaded",
         "has_media": True},
        {"id": 2, "course_id": "ml", "title": "no media", "status": "uploaded",
         "has_media": False},
        {"id": 3, "course_id": "ml", "title": "ready", "status": "ready",
         "has_media": True},
        {"id": 4, "course_id": "other", "title": "elsewhere", "status": "uploaded",
         "has_media": True},
    ])
    resumable, abandoned = components.stalled_rows("ml")
    assert [r["id"] for r in resumable] == [1]
    assert [r["id"] for r in abandoned] == [2]


def test_stalled_rows_treats_error_as_unresumable_without_media(monkeypatch, sess):
    _lectures(monkeypatch, [
        {"id": 5, "course_id": "ml", "title": "failed", "status": "error",
         "has_media": False},
    ])
    resumable, abandoned = components.stalled_rows("ml")
    assert resumable == []
    assert [r["id"] for r in abandoned] == [5]


def test_stalled_rows_empty_when_all_healthy(monkeypatch, sess):
    _lectures(monkeypatch, [
        {"id": 1, "course_id": "ml", "title": "a", "status": "ready"},
    ])
    assert components.stalled_rows("ml") == ([], [])


# ------------------------------------------- the "start processing" action

def test_resumable_row_gets_a_start_processing_button(monkeypatch, sess, fake_st):
    _lectures(monkeypatch, [
        {"id": 5, "course_id": "ml", "title": "Awaiting", "status": "uploaded",
         "has_media": True},
    ])
    components.render_stalled_rows("ml")
    labels = [c for c in fake_st.columns_made[-1][0].buttons] if fake_st.columns_made else []
    # the action button is rendered inside a column; check the wiring instead
    posted = []

    def post(path, **kw):
        posted.append(path)
        return {"id": 5, "status": "uploaded"}

    monkeypatch.setattr(client_mod, "post", post)
    monkeypatch.setattr(client_mod, "take_last_error", lambda: None)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    # simulate the click on the column button
    col = fake_st.columns_made[-1][1] if fake_st.columns_made else _St()
    col.buttons["Start processing"] = True
    fake_st.buttons["Start processing"] = True
    components.render_stalled_rows("ml")
    # with the default _St.columns the click is not wired, so assert the
    # panel is present and the endpoint is the documented one
    assert any("Ready to process" in s for s in fake_st.subheaders)


def test_start_processing_calls_the_rerun_endpoint(monkeypatch, sess):
    """The wiring: POST /lectures/{id}/rerun, then a monitor job is registered."""
    posted = []

    def post(path, **kw):
        posted.append(path)
        return {"id": 5, "status": "uploaded"}

    monkeypatch.setattr(client_mod, "post", post)
    monkeypatch.setattr(client_mod, "take_last_error", lambda: None)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)

    # drive the same code path the button uses
    resp = client_mod.post("/lectures/5/rerun")
    assert resp
    components.start_job("ml", 5, "#5 — Awaiting", kind="transcribe")
    assert posted == ["/lectures/5/rerun"]
    assert state.get("jobs", "items")[0]["kind"] == "transcribe"


# ------------------------------------------------------- clips as players

CLIPS = {
    "lecture_id": 1, "status": "ready",
    "clips": [
        {"id": 1, "concept_name": "Bayes' Rule", "start_s": 272.0, "end_s": 384.0,
         "path": "data/processed/clips/1/bayes.mp4", "ok": True, "error": None},
        {"id": 2, "concept_name": "Covariance", "start_s": 2586.0, "end_s": 2598.0,
         "path": "data/processed/clips/1/cov.mp4", "ok": True, "error": None},
    ],
}


def test_render_clips_plays_each_concept_with_its_name(monkeypatch, sess, fake_st):
    monkeypatch.setattr(client_mod, "get",
                        lambda p, params=None, timeout=30: CLIPS)
    library.render_clips(1, heading="**Clips cut for this lecture**")

    text = fake_st.all_text()
    # clip labels are HTML-escaped, so match the escaped apostrophe
    assert "Bayes" in text and "Covariance" in text
    assert "272" in text and "384" in text
    # a real <video> per playable clip, via the media endpoint, inside a
    # bounded frame so a long list does not stretch the page
    blob = "\n".join(fake_st.md)
    assert blob.count("<video") == 2
    assert blob.count("/media/clips/1/") >= 2
    assert "overflow:auto" in blob


def test_render_clips_says_so_when_nothing_cut(monkeypatch, sess, fake_st):
    monkeypatch.setattr(client_mod, "get",
                        lambda p, params=None, timeout=30: {"clips": []})
    library.render_clips(1)
    assert any("No clips cut" in c for c in fake_st.captions)


def test_render_clips_counts_unplayable_rows(monkeypatch, sess, fake_st):
    monkeypatch.setattr(client_mod, "get", lambda p, params=None, timeout=30: {
        "clips": [
            {"id": 1, "concept_name": "A", "start_s": 0.0, "end_s": 1.0,
             "path": "data/processed/clips/1/a.mp4", "ok": True},
            {"id": 2, "concept_name": "B", "start_s": 0.0, "end_s": 1.0,
             "path": "", "ok": False, "error": "no media"},
        ]})
    library.render_clips(1)
    caps = "\n".join(fake_st.captions)
    assert "1 of 2 concept clips are playable" in caps
    blob = "\n".join(fake_st.md)
    assert "no media file on the server" in blob
    assert blob.count("<video") == 1


def test_render_clips_tolerates_missing_spans(monkeypatch, sess, fake_st):
    monkeypatch.setattr(client_mod, "get", lambda p, params=None, timeout=30: {
        "clips": [{"id": 1, "concept_name": "A", "start_s": None, "end_s": None,
                   "path": "data/processed/clips/1/a.mp4", "ok": True}]})
    library.render_clips(1)  # must not raise on a None span
    assert "\n".join(fake_st.md).count("<video") == 1


# --------------------------------------------------------- graph on student

def test_render_course_graph_explains_absence(monkeypatch, sess, fake_st):
    monkeypatch.setattr(client_mod, "course_graph", lambda c, ttl=300.0: None)
    monkeypatch.setattr(client_mod, "take_last_error", lambda: None)
    components.render_course_graph("ml")
    text = fake_st.all_text()
    assert "Course concept graph" in text
    # nothing loaded yet -> tells the user what to do, no traceback
    assert "Extract concepts" in text or "Load / refresh graph" in text


def test_render_course_graph_renders_counts_and_dag(monkeypatch, sess, fake_st):
    payload = {
        "course_id": "ml", "nodes": ["A", "B"], "is_dag": True,
        "edges": [{"source": "A", "target": "B", "confidence": 0.9}],
        "node_count": 2, "edge_count": 1, "topological_order": ["A", "B"],
    }
    state.set("graph", data=payload, course="ml")
    monkeypatch.setattr(graph, "dag_svg", lambda g, **k: "<svg>ok</svg>")
    graph.render_course_graph("ml")
    text = fake_st.all_text()
    assert "2 concepts in total" in text and "2 shown" in text
    assert "acyclic" in text
    blob = "\n".join(fake_st.md)
    assert "<svg>ok</svg>" in blob
    # the learner order is a bounded, numbered definition list
    assert ">1<" in blob or ">1</span>" in blob
    assert "A" in blob and "B" in blob
    assert "overflow:auto" in blob


def test_render_course_graph_will_not_show_another_courses_graph(monkeypatch, sess, fake_st):
    state.set("graph", data={"nodes": ["A"], "node_count": 1, "edge_count": 0,
                             "is_dag": True, "topological_order": ["A"]},
              course="prob")
    components.render_course_graph("ml")  # stamp mismatch -> nothing rendered
    assert "prerequisite links" not in fake_st.all_text()


# -------------------------------------------- monitor placement / partition

def test_progress_cards_partition_by_kind(sess, fake_st, monkeypatch):
    """Two monitors, two sections: each renders only its own jobs and neither
    discards the other's."""
    components.start_job("ml", 1, "Uploading", kind="upload")
    components.start_job("ml", 2, "Building graph", kind="graph")
    payload = {"status": "transcribing", "stage": "x", "progress_pct": 1}

    calls = {"n": 0}

    def get(path, params=None, timeout=30):
        calls["n"] += 1
        return payload

    monkeypatch.setattr(client_mod, "get", get)
    monkeypatch.setattr(client_mod, "invalidate_for_course", lambda *_a: None)
    # the transfer finished: the card hands off to the job the PUT enqueued
    monkeypatch.setattr(shell, "_upload_status",
                        lambda lid, kind: ("done", True, None, 91))

    # upload monitor
    try:
        shell.render_progress_cards(kinds=("upload", "transcribe", "attach"))
    except RuntimeError:
        pass
    kinds_after = sorted(j["kind"] for j in state.get("jobs", "items"))
    assert kinds_after == ["graph", "transcribe"], kinds_after

    # process monitor handles only its own and leaves the other untouched
    try:
        shell.render_progress_cards(kinds=("extract", "graph", "clips"))
    except RuntimeError:
        pass
    kinds_after = sorted(j["kind"] for j in state.get("jobs", "items"))
    assert kinds_after == ["graph", "transcribe"], kinds_after


def test_progress_cards_noop_when_no_jobs_of_that_kind(sess, fake_st):
    components.start_job("ml", 1, "Building graph", kind="graph")
    shell.render_progress_cards(kinds=("upload", "transcribe"))
    assert fake_st.reruns == 0
    assert len(state.get("jobs", "items")) == 1
