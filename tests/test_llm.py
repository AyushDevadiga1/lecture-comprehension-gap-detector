"""
Tests for the LLM access layer (backend/pipeline/llm.py).

These tests NEVER hit the real Groq API or consume quota — LLM calls are
always stubbed/monkeypatched. Caching tests use a temporary SQLite DB so
the real data/lecgap.db is never touched either.
"""

import os
import sys
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
