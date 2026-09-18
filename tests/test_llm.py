"""
Tests for the LLM access layer (backend/pipeline/llm.py).

These tests NEVER hit the real Groq API or consume quota — LLM calls are
always stubbed/monkeypatched. Caching tests use a temporary SQLite DB so
the real data/lecgap.db is never touched either.
"""

import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{REPO / 'data' / 'test_lecgap.db'}"


@pytest.fixture(autouse=True)
def clean_cache_db():
    from backend.models import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as s:
        s.query(dbmod.LLMCache).delete()
        s.commit()
    yield
    # re-init default once at the end
    os.environ.pop("LECGAP_DATABASE_URL", None)
def test_cache_key_is_stable_and_input_sensitive():
    from backend.pipeline.llm import _cache_key

    k1 = _cache_key("m", "sys", "usr", 500, 0.0)
    k2 = _cache_key("m", "sys", "usr", 500, 0.0)
    assert k1 == k2
    assert k1 != _cache_key("m", "sys", "usr2", 500, 0.0)
    assert k1 != _cache_key("m2", "sys", "usr", 500, 0.0)


def test_empty_completion_is_not_cached_and_is_retried(monkeypatch):
    from backend.pipeline import llm

    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    calls = []

    def fake_groq(system, user, max_tokens, temperature):
        calls.append(user)
        if len(calls) == 1:
            return llm.LLMResult("", "groq", "model-x", False, 10, 0)
        return llm.LLMResult("real-answer", "groq", "model-x", False, 10, 5)

    monkeypatch.setattr(llm, "_call_groq", fake_groq)

    r1 = llm.complete("sys", "hi")
    r2 = llm.complete("sys", "hi")

    assert r1.text == "real-answer"       # empty attempt transparently retried
    assert not r1.cached
    assert r2.cached is True              # second call served from cache -> no poison
    assert len(calls) == 2


def test_cache_serves_repeat_call_from_cache(monkeypatch):
    from backend.models import db as dbmod
    from backend.pipeline import llm

    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    calls = []

    def fake_groq(system, user, max_tokens, temperature):
        calls.append(user)
        return llm.LLMResult("stub-response", "groq", "model-x", False, 10, 5)

    monkeypatch.setattr(llm, "_call_groq", fake_groq)

    r1 = llm.complete("sys", "hello")
    r2 = llm.complete("sys", "hello")

    assert r1.cached is False
    assert r2.cached is True
    assert r1.text == r2.text == "stub-response"
    assert len(calls) == 1  # only the first call reached the fake backend


def test_complete_calls_groq_then_falls_back_to_ollama(monkeypatch):
    from backend.pipeline import llm

    def failing_groq(*a, **k):
        raise RuntimeError("boom")

    def fake_ollama(system, user, max_tokens, temperature):
        return llm.LLMResult("ollama-answer", "ollama", "llama", False, 5, 5)

    monkeypatch.setattr(llm, "_call_groq", failing_groq)
    monkeypatch.setattr(llm, "_ollama_reachable", lambda: True)
    monkeypatch.setattr(llm, "_call_ollama", fake_ollama)

    result = llm.complete("sys", "hi")
    assert result.backend == "ollama"
    assert result.text == "ollama-answer"


def test_backend_status_reports_configured_flags():
    from backend.pipeline import llm

    st = llm.backend_status()
    assert "groq_configured" in st
    assert "ollama_reachable" in st
    assert isinstance(st["groq_configured"], bool)


def test_parse_reset_seconds_handles_all_units():
    from backend.pipeline.llm import _parse_reset_seconds

    assert _parse_reset_seconds("644ms") == pytest.approx(0.644)
    assert _parse_reset_seconds("500ms") == pytest.approx(0.5)  # 'ms' beat 'm'
    assert _parse_reset_seconds("1m26.4s") == pytest.approx(86.4)
    assert _parse_reset_seconds("2h3m45s") == pytest.approx(7425.0)
    assert _parse_reset_seconds("60s") == pytest.approx(60.0)
    assert _parse_reset_seconds("") == 0.0


def test_concurrent_same_key_calls_backend_once(monkeypatch):
    """Single-flight: N threads missing the same key share ONE backend call."""
    import threading

    from concurrent.futures import ThreadPoolExecutor

    from backend.pipeline import llm

    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    call_guard = threading.Lock()
    calls = []

    def fake_groq(system, user, max_tokens, temperature):
        with call_guard:
            calls.append(user)
        time.sleep(0.05)  # widen the window where a race would double-call
        return llm.LLMResult("shared-answer", "groq", "model-x", False, 10, 5)

    monkeypatch.setattr(llm, "_call_groq", fake_groq)

    def worker():
        return llm.complete("sys", "same user prompt")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: worker(), range(8)))

    assert len(calls) == 1  # the duplicate call is eliminated
    assert all(r.text == "shared-answer" for r in results)
    # the lock holder produces a fresh result; waiters are served from cache
    assert sum(r.cached for r in results) == 7
    assert sum(not r.cached for r in results) == 1


def test_cache_put_uses_insert_not_ignore_idempotent(monkeypatch):
    """A duplicate PK insert (cross-process race) must be a no-op, not raise."""
    from backend.models import db as dbmod
    from backend.pipeline import llm

    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-test")
    key = llm._cache_key(llm.GROQ_MODEL, "sys", "dup", 1000, 0.0)
    res = llm.LLMResult("first", "groq", "model-x", False, 10, 5)

    llm._cache_put(key, res)
    llm._cache_put(key, res)  # second write for the same key: no IntegrityError

    with dbmod.SessionLocal() as s:
        row = s.get(dbmod.LLMCache, key)
        assert row is not None
        assert row.response_text == "first"
