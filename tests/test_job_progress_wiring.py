"""C3 — the pipeline workers publish to the durable job registry.

Every progress publish inside a worker must reach BOTH stores: the legacy
in-memory per-lecture entry the shipped Streamlit UI reads, and the persisted
``jobs`` row that survives a restart and feeds the SSE stream.

The mechanism is a thread-local job scope rather than an extra argument on each
of the ~20 ``update_lecture_progress`` call sites - a per-call-site argument is
exactly the kind of change that gets applied to 19 of 20 sites.
"""

import threading

import pytest

from backend.api import job_registry as registry
from backend.api.jobs import progress as progress_mod
from backend.api.jobs.progress import (
    _finish,
    get_lecture_progress,
    job_scope,
    update_lecture_progress,
)
from backend.models.db import Job, SessionLocal, init_db


@pytest.fixture(autouse=True)
def clean():
    # Nothing here imports backend.main, so nothing has run init_db(); the
    # hermetic temp database has no schema yet.
    init_db()
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    with progress_mod._progress_lock:
        progress_mod._lecture_progress.clear()
    yield
    with SessionLocal() as db:
        db.query(Job).delete()
        db.commit()
    with progress_mod._progress_lock:
        progress_mod._lecture_progress.clear()


# ------------------------------------------------------------- the scope

def test_scope_binds_the_job_id():
    job_id = registry.create_job("x", course_id="ml", lecture_id=1)
    with job_scope(job_id):
        update_lecture_progress(1, "probing", 10, "scanning")
    j = registry.get_job(job_id)
    assert j["stage"] == "probing"
    assert j["progress_pct"] == 10
    assert j["status"] == "running"


def test_scope_is_undone_on_exit():
    job_id = registry.create_job("x", course_id="ml", lecture_id=1)
    with job_scope(job_id):
        pass
    # outside the scope, progress must NOT reach that job any more
    update_lecture_progress(1, "after", 50, "later")
    assert registry.get_job(job_id)["stage"] != "after"


def test_nested_scopes_restore_the_outer_job():
    outer = registry.create_job("outer", course_id="ml", lecture_id=1)
    inner = registry.create_job("inner", course_id="ml", lecture_id=2)
    with job_scope(outer):
        with job_scope(inner):
            update_lecture_progress(2, "inner-stage", 20, "x")
        update_lecture_progress(1, "outer-stage", 30, "y")
    assert registry.get_job(inner)["stage"] == "inner-stage"
    assert registry.get_job(outer)["stage"] == "outer-stage"


def test_explicit_job_id_overrides_the_scope():
    scoped = registry.create_job("scoped", course_id="ml", lecture_id=1)
    explicit = registry.create_job("explicit", course_id="ml", lecture_id=1)
    with job_scope(scoped):
        update_lecture_progress(1, "s", 10, "d", job_id=explicit)
    assert registry.get_job(explicit)["stage"] == "s"
    assert registry.get_job(scoped)["stage"] != "s"


def test_scopes_are_thread_isolated():
    """Two BackgroundTasks run concurrently; one must not inherit the other's
    job id, or a job would report another job's progress."""
    a = registry.create_job("a", course_id="ml", lecture_id=1)
    b = registry.create_job("b", course_id="ml", lecture_id=2)
    seen = {}
    started = threading.Event()

    def run(job_id, lid, key, first=False):
        with job_scope(job_id):
            if first:
                started.set()
            else:
                started.wait(2)
            update_lecture_progress(lid, f"stage-{key}", 10, key)
            seen[key] = progress_mod._active_job_id()

    t1 = threading.Thread(target=run, args=(a, 1, "a", True))
    t2 = threading.Thread(target=run, args=(b, 2, "b", False))
    t1.start(); started.wait(2); t2.start()
    t1.join(5); t2.join(5)
    assert seen == {"a": a, "b": b}


# ------------------------------------------------------- legacy + durable

def test_both_stores_are_written():
    job_id = registry.create_job("x", course_id="ml", lecture_id=7)
    with job_scope(job_id):
        update_lecture_progress(7, "transcribing", 42, "decoding")
    legacy = get_lecture_progress(7)
    assert legacy["status"] == "transcribing"
    assert legacy["stage"] == "transcribing"
    assert legacy["progress_pct"] == 42
    durable = registry.get_job(job_id)
    assert durable["stage"] == "transcribing"
    assert durable["progress_pct"] == 42


def test_legacy_behaviour_is_unchanged_without_a_job():
    update_lecture_progress(8, "extracting", 20, "working")
    d = get_lecture_progress(8)
    assert d["status"] == "extracting"
    assert d["stage"] == "extracting"
    assert d["progress_pct"] == 20


def test_status_is_derived_from_the_stage_when_omitted():
    """The parameter used to default to the literal "transcribing", so an
    omitted status stored status="transcribing" beside stage="building_graph"."""
    for stage, expected in [
        ("extracting", "extracting"),
        ("building_graph", "building_graph"),
        ("cutting_clips", "clips"),
        ("local_transcribing", "transcribing"),
        ("uploading", "uploading"),
    ]:
        lid = 100 + abs(hash(stage)) % 50
        update_lecture_progress(lid, stage, 5, "d")
        d = get_lecture_progress(lid)
        assert d["status"] == expected, (stage, d["status"])
        assert d["stage"] == stage


def test_explicit_status_still_wins():
    update_lecture_progress(120, "saving_segments", 95, "d",
                           status="transcribing")
    d = get_lecture_progress(120)
    assert d["status"] == "transcribing" and d["stage"] == "saving_segments"


def test_finish_settles_the_durable_row():
    job_id = registry.create_job("x", course_id="ml", lecture_id=7)
    with job_scope(job_id):
        update_lecture_progress(7, "saving", 90, "almost")
        _finish(7)
    j = registry.get_job(job_id)
    assert j["status"] == "ready", "a finished worker must not leave the job running"
    assert j["terminal"] is True


def test_finish_does_not_downgrade_a_settled_error():
    job_id = registry.create_job("x", course_id="ml", lecture_id=7)
    with job_scope(job_id):
        registry.fail_job(job_id, "boom")
        _finish(7)
    assert registry.get_job(job_id)["status"] == "error"


def test_fail_settles_both_stores():
    job_id = registry.create_job("x", course_id="ml", lecture_id=7)
    with job_scope(job_id):
        update_lecture_progress(7, "s", 10, "d")
        progress_mod.fail(7, error="stage exploded")
    assert registry.get_job(job_id)["status"] == "error"
    assert "exploded" in registry.get_job(job_id)["error"]


@pytest.mark.parametrize("status,expected", [
    ("ready", "ready"),
    ("error", "error"),
    ("transcribing", "running"),
    ("extracting", "running"),
    ("building_graph", "running"),
    ("clips", "running"),
    ("uploading", "running"),
])
def test_pipeline_status_maps_onto_the_job_state_machine(status, expected):
    job_id = registry.create_job("x", course_id="ml", lecture_id=7)
    with job_scope(job_id):
        update_lecture_progress(7, "s", 10, "d", status=status)
    assert registry.get_job(job_id)["status"] == expected


# ------------------------------------------------- every worker is covered

def test_all_four_workers_accept_a_job_id():
    import inspect

    from backend.api.jobs import clips, extract, graph, transcribe

    for mod, fn in [
        (transcribe, "process_lecture"),
        (extract, "extract_concepts_worker"),
        (clips, "cut_clips_worker"),
        (graph, "build_course_graph_worker"),
    ]:
        sig = inspect.signature(getattr(mod, fn))
        assert "job_id" in sig.parameters, f"{mod.__name__}.{fn} has no job_id"
        assert sig.parameters["job_id"].default is None, \
            f"{mod.__name__}.{fn} must keep job_id optional"


def test_every_worker_binds_the_scope():
    import inspect

    from backend.api.jobs import clips, extract, graph, transcribe

    for mod, fn in [
        (transcribe, "process_lecture"),
        (extract, "extract_concepts_worker"),
        (clips, "cut_clips_worker"),
        (graph, "build_course_graph_worker"),
    ]:
        src = inspect.getsource(getattr(mod, fn))
        assert "job_scope(job_id)" in src, f"{mod.__name__}.{fn} never binds the scope"


def test_routes_enqueue_through_the_registry():
    """The enqueue helper must create the row and pass the id to the worker."""
    import inspect

    from backend.api.routes import lectures

    src = inspect.getsource(lectures)
    assert "registry.create_job(" in src
    assert "job_id=job_id" in src


def test_graph_route_returns_the_job_id():
    import inspect

    from backend.api.routes import courses

    src = inspect.getsource(courses.build_course_graph)
    assert "registry.create_job(" in src
    assert "job_id=job_id" in src
