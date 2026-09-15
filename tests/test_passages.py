"""Stage 2 — Lecture Structure pass (backend/pipeline/passages.py).

Covers the sliding-window builder (boundaries + overlap), the JSON parse +
clamp contract, the caps, and the ONE-call-per-window guarantee that replaces
the old per-concept scatter. No network: `completer` is injected everywhere.
"""

from types import SimpleNamespace

import pytest

from backend.pipeline import passages
from backend.pipeline.llm import LLMResult

W = passages.WINDOW_CHARS


def _result(text):
    return LLMResult(text=text, backend="fake", model="fake", cached=True)


def _seg(st, en, text):
    return {"start_s": float(st), "end_s": float(en), "text": text}


def _docs(n_segs, secs_per_seg=20.0, chars_per_seg=200):
    return [
        _seg(i * secs_per_seg, (i + 1) * secs_per_seg, f"tok{i} " + "x" * chars_per_seg)
        for i in range(n_segs)
    ]


# -------------------------------------------------------------- window builder

def test_window_empty_docs_no_windows():
    assert passages._window_excerpts([], W, passages.OVERLAP_FRAC) == []


def test_window_single_window_when_small():
    out = passages._window_excerpts(_docs(5), W, passages.OVERLAP_FRAC)
    assert len(out) == 1
    assert out[0]["start_s"] == 0.0
    assert out[0]["end_s"] == 100.0
    assert "tok0" in out[0]["text"] and "tok4" in out[0]["text"]


def test_window_overlap_covers_boundary():
    out = passages._window_excerpts(_docs(120), W, passages.OVERLAP_FRAC)
    assert len(out) >= 2
    for a, b in zip(out, out[1:]):
        assert b["start_s"] < a["end_s"], "next window must re-read the tail"
    assert out[0]["start_s"] == 0.0
    assert out[-1]["end_s"] == 120 * 20.0  # full coverage
    assert len(set(w["start_s"] for w in out)) == len(out)  # strictly advancing

def test_window_advances_and_ends():
    out = passages._window_excerpts(_docs(120), W, passages.OVERLAP_FRAC)
    assert len(out) >= 2
    assert out[-1]["end_s"] == 120 * 20.0


def test_window_single_when_text_fits_budget():
    out = passages._window_excerpts(_docs(30), W, passages.OVERLAP_FRAC)
    assert len(out) == 1
    assert out[0]["end_s"] == 600.0


# ------------------------------------------------------------------ parsing

def test_parse_json_strips_fences():
    canned = 'Sure! \n```json\n{"passages": [{"title": "A", "start_s": 0.0, "end_s": 10.0}]}\n```'
    assert passages._parse_json(canned)["passages"][0]["title"] == "A"


def test_parse_json_garbage_is_none():
    assert passages._parse_json("no json here") is None
    assert passages._parse_json("{}") == {}  # no 'passages' key -> caller rejects


def test_parse_passages_clamps_to_window():
    ex = {"start_s": 100.0, "end_s": 200.0, "text": "..."}
    canned = ('{"passages": [{"title": "P", "kind": "explain", "start_s": 0.0, '
              '"end_s": 300.0, "summary": "", "continues": false, "concepts": '
              '[{"name": "c", "implicit": false, "teach_start_s": 50.0, '
              '"teach_end_s": 999.0}]}]}')
    p = passages._parse_passages(canned, ex)
    assert p[0]["start_s"] == 100.0
    assert p[0]["end_s"] == 200.0
    assert p[0]["concepts"][0]["teach_start_s"] == 100.0
    assert p[0]["concepts"][0]["teach_end_s"] == 200.0


def test_parse_passages_drops_invalid():
    ex = {"start_s": 0.0, "end_s": 100.0, "text": ""}
    canned = ('{"passages": [{"title": "ok", "kind": "define", "start_s": 0.0, '
              '"end_s": 10.0, "continues": false}, '
              '{"kind": "define", "start_s": 0.0, "end_s": 10.0}, '
              '{"title": "bad-times", "kind": "explain", "start_s": 50.0, "end_s": 40.0}, '
              '{"title": "bad-kind", "kind": "livestream", "start_s": 0.0, "end_s": 10.0}]}')
    p = passages._parse_passages(canned, ex)
    assert [x["title"] for x in p] == ["ok", "bad-kind"]
    assert p[1]["kind"] == "explain"  # unknown kind normalized


def test_parse_passages_enforces_caps():
    import json
    ex = {"start_s": 0.0, "end_s": 100.0, "text": ""}
    passages_lst = [
        {"title": f"t{i}", "kind": "explain", "start_s": 0.0, "end_s": 10.0,
         "concepts": [{"name": f"c{i}{j}", "implicit": False,
                       "teach_start_s": 1.0, "teach_end_s": 9.0} for j in range(9)],
         "links": [{"from": f"c{i}{j}", "to": f"c{i}{j + 1}", "evidence": "q"}
                   for j in range(12)]}
        for i in range(7)
    ]
    p = passages._parse_passages('{"passages": %s}' % json.dumps(passages_lst), ex)
    assert len(p) == passages.MAX_PASSAGES
    for x in p:
        assert len(x["concepts"]) == passages.MAX_CONCEPTS_PER_PASSAGE
        assert len(x["links"]) == passages.MAX_LINKS


# --------------------------------------------------------- end-to-end assembly

class _FakeCompleter:
    """Returns canned per-window output for the excerpt's first segment time."""

    def __init__(self, by_window):
        self.by_window = by_window
        self.calls = []

    def __call__(self, system, prompt, temperature, max_tokens):
        self.calls.append(prompt)
        excerpt_line = prompt.split("Transcript excerpt")[1]
        a = float(excerpt_line.split("[")[1].split("-")[0])
        out = self.by_window.get(round(a))
        assert out is not None, f"no canned answer for window@{a}"
        return _result(out)


def _one_passage(title, s, e, concepts=None, kind="explain", continues=False):
    return {"title": title, "kind": kind, "start_s": s, "end_s": e,
            "summary": title + " taught", "continues": continues,
            "links": [], "concepts": concepts or []}


def test_extract_one_call_per_window():
    docs = _docs(120)  # ~5 windows
    fake = _FakeCompleter({
        w["start_s"]: '{"passages": [{"title": "p", "kind": "explain", '
                       '"start_s": ' + str(w["start_s"]) + ', "end_s": ' +
                       str(w["end_s"]) + ', "continues": false, "links": [], '
                       '"concepts": []}]}'
        for w in passages._window_excerpts(docs, W, passages.OVERLAP_FRAC)
    })
    out = passages.extract_lecture_structure(docs, fake)
    n_windows = len(passages._window_excerpts(docs, W, passages.OVERLAP_FRAC))
    assert len(fake.calls) == n_windows  # never per-concept
    assert out["passages"]


def test_extract_assembles_concepts_and_links():
    docs = _docs(4)
    fake = _FakeCompleter({
        0.0: '{"passages": [{"title": "pure pydantic basics", "kind": "define", '
             '"start_s": 0.0, "end_s": 80.0, "summary": "", "continues": false, '
             '"concepts": [{"name": "data binding", "implicit": false, '
             '"teach_start_s": 5.0, "teach_end_s": 40.0}], '
             '"links": [{"from": "data binding", "to": "validation", '
             '"evidence": "recall"}]}]}'
    })
    out = passages.extract_lecture_structure(docs, fake)
    assert [c["name"] for c in out["concepts"]] == ["data binding"]
    assert out["concepts"][0]["start_s"] == 5.0  # teach-span, not chunk stamp
    assert out["concepts"][0]["passage_index"] == 0
    assert out["links"][0]["evidence"] == "recall"
    assert "tok0" in out["passages"][0]["text"]


def test_extract_merges_boundary_duplicate():
    import json
    docs = _docs(120)
    canned_by_win = {}
    for w in passages._window_excerpts(docs, W, passages.OVERLAP_FRAC):
        canned_by_win[w["start_s"]] = (
            '{"passages": %s}' % json.dumps([
                _one_passage("the same topic", w["start_s"], w["end_s"], [],
                             continues=False)
            ])
        )
    fake = _FakeCompleter(canned_by_win)
    out = passages.extract_lecture_structure(docs, fake)
    assert len(out["passages"]) == 1  # every window picked the same span -> collapsed
    assert out["passages"][0]["start_s"] == 0.0
    assert out["passages"][0]["end_s"] == 120 * 20.0


def test_extract_completer_failure_degrades_gracefully():
    def boom(*a, **k):
        raise RuntimeError("quota")
    out = passages.extract_lecture_structure(_docs(4), boom)
    assert out == {"passages": [], "concepts": [], "links": []}


def test_extract_empty_docs_no_calls():
    calls = []

    def completer(*a, **k):
        calls.append(1)
        return _result("{}")
    out = passages.extract_lecture_structure([], completer)
    assert out == {"passages": [], "concepts": [], "links": []}
    assert calls == []


def test_completer_injection_matches_llm_signature():
    import inspect
    sig = inspect.signature(passages.extract_lecture_structure)
    assert sig.parameters["completer"] is not None  # injectable for tests