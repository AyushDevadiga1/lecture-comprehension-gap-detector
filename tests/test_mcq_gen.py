"""Stage 6c — LLM-generated MCQs (backend/pipeline/mcq_gen.py).

Covers the JSON parser contract (well-formed -> graded dict, anything else ->
None so callers fall back to evidence), the transcript-window selection for
`local_context`, and the failure isolation of `generate_mcq` (never raises).
No network: `completer` is injected everywhere.
"""

from types import SimpleNamespace

import pytest

from backend.pipeline import mcq_gen
from backend.pipeline.llm import LLMResult

_GOOD = '{"question": "What is attention?", "answer": "a learned weight over inputs", ' \
        '"distractors": ["random noise", "a loss function", "an optimizer"], ' \
        '"explanation": "attention weights the inputs by relevance, so it is a learned ratio", ' \
        '"rationales": ["noise is not a learned structure", ' \
                       '"a loss is what you optimize, not what attention computes", ' \
                       '"an optimizer updates the weights, it is not the attention mechanism"]}'


def _result(text):
    return LLMResult(text=text, backend="fake", model="fake", cached=True)


def _seg(st, en, text):
    return SimpleNamespace(start_s=st, end_s=en, text=text)


# ------------------------------------------------------------- local_context

def test_local_context_anchors_on_concept_window():
    segs = [_seg(0, 2, "intro"), _seg(2, 4, "attention is a weighted sum"),
            _seg(4, 6, "we backprop toward it")]
    c = SimpleNamespace(name="attention", start_s=2.3, end_s=5.0)
    ctx = mcq_gen.local_context(segs, c)
    assert "attention is a weighted sum" in ctx
    assert "we backprop toward it" in ctx
    assert "intro" not in ctx


def test_local_context_mentions_fallback_when_no_window():
    segs = [{"text": "hello", "start_s": 0.0, "end_s": 1.0},
            {"text": "the dropout explanation here", "start_s": 1.0, "end_s": 2.0}]
    c = SimpleNamespace(name="dropout", start_s=None, end_s=None)
    assert "the dropout explanation here" in mcq_gen.local_context(segs, c)


def test_local_context_none_without_anchor_or_mention():
    segs = [_seg(0, 2, "unrelated chatter"), _seg(2, 4, "more chatter")]
    assert mcq_gen.local_context(segs, SimpleNamespace(name="lstm", start_s=None, end_s=None)) is None
    assert mcq_gen.local_context(segs, None) is None


# ------------------------------------------------------------------ parsing

def test_parse_good_json():
    q = mcq_gen._parse_mcq(_GOOD)
    assert q["question"].startswith("What is attention?")
    assert q["answer"] == "a learned weight over inputs"
    assert len(q["options"]) == 4
    assert set(q["options"]) == {"a learned weight over inputs", "random noise",
                                 "a loss function", "an optimizer"}
    # correct option is always the documented `answer`, wherever it got shuffled
    assert q["answer"] in q["options"]


def test_parse_strips_code_fences():
    q = mcq_gen._parse_mcq(f"Here you go:\n```json\n{_GOOD}\n```\nregards")
    assert q and q["answer"] == "a learned weight over inputs"


def test_parse_rejects_non_json():
    assert mcq_gen._parse_mcq("yes that is correct") is None
    assert mcq_gen._parse_mcq("") is None
    assert mcq_gen._parse_mcq(None) is None


def test_parse_skips_thinking_prefix():
    text = (
        " thinking\nLet me reason about distractors first. {A noisy brace here.\n"
        '{\n'
        '  "question": "Which best describes normalization?",\n'
        '  "answer": "It removes redundant columns.",\n'
        '  "distractors": ["It duplicates rows.", "It drops all keys.", '
        '"It indexes everything."],\n'
        '  "explanation": "Normalization eliminates redundancy.",\n'
        '  "rationales": ["Duplication is the opposite.", "Keys stay intact.", '
        '"Indexing is separate."]\n'
        "}"
    )
    q = mcq_gen._parse_mcq(text)
    assert q is not None
    assert q["answer"] == "It removes redundant columns."
    assert len(q["options"]) == 4
    assert q["explanation"]
    assert len(q["rationale"]) == 3


def test_parse_rejects_missing_fields_or_few_distractors():
    assert mcq_gen._parse_mcq('{"answer": "x", "distractors": ["a", "b", "c"]}') is None
    assert mcq_gen._parse_mcq('{"question": "q", "answer": "x", "distractors": ["a", "b"]}') is None
    assert mcq_gen._parse_mcq('{"question": "q", "answer": "x", "distractors": "nope"}') is None


def test_parse_dedupes_and_drops_answer_lookalikes():
    raw = '{"question": "q", "answer": "the truth", ' \
          '"distractors": ["a", "the truth", "a", "b"]}'
    assert mcq_gen._parse_mcq(raw) is None  # only 2 distinct usable distractors


def test_parse_keeps_explanation_and_rationales_aligned():
    q = mcq_gen._parse_mcq(_GOOD)
    assert q["explanation"] == "attention weights the inputs by relevance, " \
                              "so it is a learned ratio"
    rat = q["rationale"]
    assert rat["random noise"] == "noise is not a learned structure"
    assert rat["a loss function"] == "a loss is what you optimize, not what attention computes"
    # rationales are keyed by distractor text -> dedup/short lists can't misalign
    raw = ('{"question": "q", "answer": "truth", "distractors": ["a", "b", "c"], '
           '"rationales": ["ra"]}')
    assert mcq_gen._parse_mcq(raw)["rationale"] == {"a": "ra"}


def test_parse_ignores_explanation_when_absent():
    raw = ('{"question": "q", "answer": "truth", "distractors": ["a", "b", "c"]}')
    q = mcq_gen._parse_mcq(raw)
    assert q["explanation"] is None and q["rationale"] == {}


# --------------------------------------------------------------- generate_mcq

def test_generate_mcq_uses_completer_and_normalizes():
    calls = []

    def fake(system, user, **kw):
        calls.append((system, user, kw))
        return _result(_GOOD)

    q = mcq_gen.generate_mcq("attention", "the excerpt", completer=fake, temperature=0.5)
    assert q["answer"] == "a learned weight over inputs"
    assert q["question"].startswith("What is attention?")
    # the prompt passed the excerpt so the LLM could quote the lecture
    _, user, kw = calls[0]
    assert "attention" in user and "the excerpt" in user
    assert kw["temperature"] == 0.5


@pytest.mark.parametrize(
    "bad",
    [
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")),
        lambda *a, **k: _result("not json"),
        lambda *a, **k: _result('{"answer": "x", "distractors": ["a", "b", "c"]}'),
    ],
)
def test_generate_mcq_never_raises_and_returns_none(bad):
    assert mcq_gen.generate_mcq("attention", "ctx", completer=bad) is None


def test_generate_mcq_skips_empty_context():
    assert mcq_gen.generate_mcq("attention", None) is None
    assert mcq_gen.generate_mcq("attention", "   ") is None