"""
Tests for Stage 2 concept extraction (backend/pipeline/extract_concepts.py).

Only pure logic is tested here — no real LLM calls, no quota. The LLM is
monkeypatched for the chunking/extraction-level tests, and the helper
functions (_parse_concepts, _chunks) are tested directly with fixtures.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def test_parse_concepts_plain_json():
    from backend.pipeline.extract_concepts import _parse_concepts

    text = '{"concepts":[{"name":"Gradient Descent","implicit":false},' \
           '{"name":"Loss Function","implicit":true}]}'
    out = _parse_concepts(text)
    assert out == [
        {"name": "Gradient Descent", "implicit": False},
        {"name": "Loss Function", "implicit": True},
    ]


def test_parse_concepts_strips_code_fence():
    from backend.pipeline.extract_concepts import _parse_concepts

    text = '```json\n{"concepts":[{"name":"CNN","implicit":false}]}\n```'
    out = _parse_concepts(text)
    assert out == [{"name": "CNN", "implicit": False}]


def test_parse_concepts_skips_blank_names():
    from backend.pipeline.extract_concepts import _parse_concepts

    text = '{"concepts":[{"name":"","implicit":false},{"name":"  ","implicit":false},' \
           '{"name":"OK","implicit":false}]}'
    assert _parse_concepts(text) == [{"name": "OK", "implicit": False}]


def test_parse_concepts_invalid_json_raises():
    from backend.pipeline.extract_concepts import _parse_concepts

    with pytest.raises(ValueError):
        _parse_concepts("this is not json at all")


def test_chunks_split_at_limit():
    from backend.pipeline.extract_concepts import _chunks

    docs = [{"start_s": 0, "end_s": 1, "text": "a" * 100} for _ in range(5)]
    chunks = _chunks(docs, max_chars=250)
    # 5 docs * ~106 chars each => fits in 3 chunks
    assert len(chunks) == 3
    assert chunks[0]["start_s"] == 0
    assert chunks[-1]["end_s"] == 1


def test_chunks_single_chunk_for_small_input():
    from backend.pipeline.extract_concepts import _chunks

    docs = [{"start_s": 0.0, "end_s": 5.0, "text": "hi"}]
    chunks = _chunks(docs, max_chars=1000)
    assert len(chunks) == 1
    assert chunks[0]["start_s"] == 0.0
    assert chunks[0]["end_s"] == 5.0


def test_extract_spoken_concepts_uses_llm_once_per_chunk(monkeypatch):
    from backend.pipeline import extract_concepts as ec

    calls = []

    def fake_complete(system, user, max_tokens, temperature):
        calls.append(user)
        return type(
            "R", (), {"text": '{"concepts":[{"name":"X","implicit":false}]}'}
        )()

    monkeypatch.setattr(ec, "complete", fake_complete)

    docs = [{"start_s": 0, "end_s": 10, "text": "text" * 50} for _ in range(4)]
    result = ec.extract_spoken_concepts(docs)
    assert len(calls) == 1  # 4 docs fit in 1 chunk by default
    assert result[0]["name"] == "X"
    assert result[0]["source"] == "spoken"


def test_extract_spoken_concepts_empty_returns_empty(monkeypatch):
    from backend.pipeline import extract_concepts as ec

    monkeypatch.setattr(ec, "complete", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert ec.extract_spoken_concepts([]) == []
