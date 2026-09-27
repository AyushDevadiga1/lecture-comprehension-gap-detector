"""C0 backend regression tests — the throttle and the quiz guard.

  * PIPELINE_SEMAPHORE was documented as covering transcription, concept
    extraction, clip cutting and graph build, but only transcription acquired
    it, so a burst of clicks fanned out unbounded MiniLM loads and ffmpeg
    re-encodes. The replacement is reentrant because extract chains a graph
    rebuild, which deadlocks a plain BoundedSemaphore at
    LECGAP_MAX_PIPELINE_JOBS=1.
  * POST /quizzes deletes and recreates a course's ConceptItem rows, so two
    concurrent generations silently discarded each other's questions.
"""

import threading
import time

import pytest

from backend.api.jobs.common import _PipelineThrottle


# ------------------------------------------------------------- the throttle

def test_throttle_limits_concurrency():
    t = _PipelineThrottle(2)
    peak = []
    lock = threading.Lock()
    live = [0]

    def body():
        with t:
            with lock:
                live[0] += 1
                peak.append(live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1

    threads = [threading.Thread(target=body) for _ in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=10)
    assert max(peak) <= 2, f"throttle let {max(peak)} run at once"


def test_throttle_blocks_beyond_permits():
    t = _PipelineThrottle(1)
    t.__enter__()
    got = threading.Event()

    def body():
        with t:
            got.set()

    th = threading.Thread(target=body, daemon=True)
    th.start()
    assert not got.wait(0.2), "second holder should have been blocked"
    t.__exit__()
    assert got.wait(2), "permit was not released"


def test_throttle_is_reentrant():
    """extract -> graph nesting must not deadlock, even with one permit."""
    t = _PipelineThrottle(1)
    with t:
        with t:  # nested acquire on the same thread
            assert t.in_use == 1, "nested acquire must not consume a 2nd permit"
    assert t.in_use == 0
    # fully released, so an unrelated thread can take it
    got = threading.Event()

    def body():
        with t:
            got.set()

    th = threading.Thread(target=body, daemon=True)
    th.start()
    assert got.wait(2)


def test_throttle_releases_on_exception():
    t = _PipelineThrottle(1)
    with pytest.raises(ValueError):
        with t:
            raise ValueError("boom")
    assert t.in_use == 0


def test_throttle_never_zero_permits():
    t = _PipelineThrottle(0)
    with t:
        assert t.in_use == 1


def test_all_heavy_workers_acquire_the_throttle():
    """Every stage the throttle documents must actually take it."""
    import inspect

    from backend.api.jobs import clips, extract, graph, transcribe

    for mod, fn in [
        (transcribe, "process_lecture"),
        (extract, "extract_concepts_worker"),
        (clips, "cut_clips_worker"),
        (graph, "build_course_graph_worker"),
    ]:
        src = inspect.getsource(getattr(mod, fn))
        assert "PIPELINE_SEMAPHORE" in src, f"{mod.__name__}.{fn} bypasses the throttle"


def test_throttled_workers_delegate_without_recursion():
    """The wrapper/inner split must not let the wrapper call itself.

    Checked with the AST: a substring test would be fooled by
    ``_extract_concepts_worker`` containing ``extract_concepts_worker``.
    """
    import ast
    import inspect

    from backend.api.jobs import clips, extract, graph

    for mod, pub, inner in [
        (extract, "extract_concepts_worker", "_extract_concepts_worker"),
        (clips, "cut_clips_worker", "_cut_clips_worker"),
        (graph, "build_course_graph_worker", "_build_course_graph_worker"),
    ]:
        assert hasattr(mod, inner), f"{mod.__name__} is missing {inner}"
        tree = ast.parse(inspect.getsource(getattr(mod, pub)).lstrip())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == pub)
        called = {c.func.id for c in ast.walk(fn)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert pub not in called, f"{pub} recurses into itself"
        assert inner in called, f"{pub} must delegate to {inner}"


# --------------------------------------------------------- the quiz guard

def test_quiz_lock_is_per_course():
    from backend.api.routes.quizzes import _quiz_lock

    a = _quiz_lock("course-a")
    b = _quiz_lock("course-b")
    assert a is not b
    assert _quiz_lock("course-a") is a, "same course must reuse one lock"


def test_quiz_lock_excludes_concurrent_generation():
    from backend.api.routes.quizzes import _quiz_lock

    lock = _quiz_lock("race-course")
    assert lock.acquire(blocking=False) is True
    try:
        # a second request for the same course must be refused immediately
        assert lock.acquire(blocking=False) is False
    finally:
        lock.release()
    assert lock.acquire(blocking=False) is True
    lock.release()


def test_create_quiz_409s_while_another_generation_runs(monkeypatch):
    """The endpoint must answer 409, not queue silently behind the first run."""
    from fastapi import HTTPException

    from backend.api.routes import quizzes

    lock = quizzes._quiz_lock("busy-course")
    assert lock.acquire(blocking=False) is True
    called = []

    def boom(*a, **k):
        called.append(1)
        raise AssertionError("must not reach generation while the lock is held")

    monkeypatch.setattr(quizzes, "_create_quiz", boom)
    try:
        with pytest.raises(HTTPException) as exc:
            quizzes.create_quiz(course_id="busy-course", student_id="s1")
        assert exc.value.status_code == 409
        assert "already being generated" in exc.value.detail
        assert called == []
    finally:
        lock.release()


def test_create_quiz_releases_the_lock_on_success(monkeypatch):
    from backend.api.routes import quizzes

    sentinel = object()
    monkeypatch.setattr(quizzes, "_create_quiz",
                        lambda c, s, m=None: (sentinel, c, s, m))
    assert quizzes.create_quiz(course_id="ok-course", student_id="s1")[0] is sentinel
    # released, so the next request is admitted
    assert quizzes.create_quiz(course_id="ok-course", student_id="s2")[0] is sentinel


def test_create_quiz_releases_the_lock_on_failure(monkeypatch):
    from backend.api.routes import quizzes

    def boom(c, s, m=None):
        raise RuntimeError("generation exploded")

    monkeypatch.setattr(quizzes, "_create_quiz", boom)
    with pytest.raises(RuntimeError):
        quizzes.create_quiz(course_id="err-course", student_id="s1")
    # the lock must not stay held after an exception
    assert quizzes._quiz_lock("err-course").acquire(blocking=False) is True
    quizzes._quiz_lock("err-course").release()


def test_max_questions_is_passed_through(monkeypatch):
    from backend.api.routes import quizzes

    seen = {}
    monkeypatch.setattr(quizzes, "_create_quiz",
                        lambda c, s, m=None: seen.update(m=m) or None)
    quizzes.create_quiz(course_id="cap-course", student_id="s1", max_questions=7)
    assert seen["m"] == 7


def test_spread_sample_covers_the_whole_course():
    from backend.api.routes.quizzes import _spread_sample

    names = [f"c{i}" for i in range(100)]
    picked = _spread_sample(names, 10)
    assert len(picked) == 10
    assert picked[0] == "c0", "must start at the first concept"
    assert picked[-1] == "c99", "must reach the last concept"
    # evenly spread across the whole range, not a prefix
    idx = [int(n[1:]) for n in picked]
    gaps = [b - a for a, b in zip(idx, idx[1:])]
    assert max(gaps) - min(gaps) <= 1, f"uneven spread: {gaps}"


def test_spread_sample_edge_cases():
    from backend.api.routes.quizzes import _spread_sample

    names = [f"c{i}" for i in range(5)]
    assert _spread_sample(names, 0) == names
    assert _spread_sample(names, 99) == names
    assert len(_spread_sample(names, 5)) == 5
    assert len(_spread_sample(names, 1)) == 1
