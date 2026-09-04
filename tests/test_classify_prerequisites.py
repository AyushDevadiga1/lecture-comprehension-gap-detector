"""
Unit tests for Stage 3 prerequisite classification
(backend/pipeline/classify_prerequisites.py) — the project's technical core.

Unlike scripts/evaluate_classifier.py (a heavyweight 5-fold CV benchmark that
downloads MiniLM + loads LectureBank), these tests are hermetic and fast:
sentence_transformers is monkeypatched with a tiny constant-vector encoder, so
no model download, no LectureBank files, no quota — exactly like how
test_build_graph.py monkeypatches the graph encoder.

Covers: candidate-pair pre-filter (temporal + similarity), the feature
assembler (shape + interaction block), the frozen-encoder + logistic-head
classifier (fit / predict_proba / predict), the LLM second-opinion pass, and
the course bridge.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.pipeline import classify_prerequisites as CP  # noqa: E402


# ---------------------------------------------------------------------------
# Hermetic sentence_transformers stand-ins
# ---------------------------------------------------------------------------

class _FakeEncoder:
    """Deterministic name->vector map so fits/predicts are reproducible."""

    _DIMS = 4

    def __init__(self, *_args, **_kwargs):
        self._cache = {}

    def _vec(self, name):
        if name not in self._cache:
            rng = np.random.RandomState(abs(hash(name)) % (2**32))
            self._cache[name] = rng.rand(self._DIMS).astype(np.float32)
        return self._cache[name]

    def encode(self, names, convert_to_tensor=False):
        return np.stack([self._vec(n) for n in names])


class _FakeUtil:
    @staticmethod
    def cos_sim(a, b):
        an = np.asarray(a, dtype=float).reshape(1, -1)
        bn = np.asarray(b, dtype=float).reshape(1, -1)
        na = np.linalg.norm(an)
        nb = np.linalg.norm(bn)
        dot = float(an.ravel() @ bn.ravel())
        return np.array([[dot / float(max(na * nb, 1e-8))]])


def _stub_st():
    return _FakeEncoder, _FakeUtil


# ---------------------------------------------------------------------------
# get_candidate_pairs — temporal + embedding pre-filter
# ---------------------------------------------------------------------------

def test_candidate_pairs_by_time_window(monkeypatch):
    monkeypatch.setattr(CP, "_st", _stub_st)
    concepts = [
        {"name": "A", "start_s": 0.0},
        {"name": "B", "start_s": 10.0},
        {"name": "C", "start_s": 5000.0},  # far in time, low sim -> excluded
    ]
    pairs = CP.get_candidate_pairs(concepts, time_window_s=120.0, sim_threshold=1.1)
    assert ("A", "B") in pairs
    assert ("B", "A") in pairs  # both directions
    assert all("C" not in p for p in pairs)


def test_candidate_pairs_ignores_missing_timestamps():
    concepts = [{"name": "A", "start_s": 0.0}, {"name": "B", "start_s": None}]
    pairs = CP.get_candidate_pairs(concepts, time_window_s=120.0, sim_threshold=1.1)
    assert pairs == []


def test_candidate_pairs_skips_self_and_duplicates(monkeypatch):
    monkeypatch.setattr(CP, "_st", _stub_st)
    concepts = [{"name": "A", "start_s": 0.0}]
    pairs = CP.get_candidate_pairs(concepts, time_window_s=120.0, sim_threshold=0.0)
    assert ("A", "A") not in pairs


def test_candidate_pairs_semantic_similarity(monkeypatch):
    monkeypatch.setattr(CP, "_st", _stub_st)
    # Far apart in time but identical names (cos >= sim_threshold) -> candidate.
    concepts = [
        {"name": "Gradient Descent", "start_s": 0.0},
        {"name": "Gradient Descent", "start_s": 9000.0},
    ]
    pairs = CP.get_candidate_pairs(concepts, time_window_s=10.0, sim_threshold=0.0)
    assert len(pairs) == 1  # self-pair dropped even though cos=1.0


# ---------------------------------------------------------------------------
# _pair_features — assembler shape + interaction block
# ---------------------------------------------------------------------------

def _cached_vecs(names):
    rng = np.random.RandomState(0)
    return {n: rng.rand(4).astype(np.float32) for n in names}


def test_pair_features_shape_with_interactions():
    vecs = _cached_vecs(["A", "B"])
    X = CP._pair_features([("A", "B")], vecs, interactions=True)
    # A + B + |A-B| + A*B + cosine = 4 + 4 + 4 + 4 + 1
    assert X.shape == (1, 2 * 4 + 2 * 4 + 1)


def test_pair_features_shape_without_interactions():
    vecs = _cached_vecs(["A", "B"])
    X = CP._pair_features([("A", "B")], vecs, interactions=False)
    assert X.shape == (1, 2 * 4)


def test_pair_features_vector_order_tracks_pairs():
    vecs = _cached_vecs(["A", "B"])
    X = CP._pair_features([("A", "B"), ("B", "A")], vecs, interactions=False)
    # first block of row 0 is vec(A); first block of row 1 is vec(B)
    np.testing.assert_allclose(X[0, :4], vecs["A"])
    np.testing.assert_allclose(X[1, :4], vecs["B"])


# ---------------------------------------------------------------------------
# PrerequisiteClassifier — fit / predict_proba / predict
# ---------------------------------------------------------------------------

@pytest.fixture
def clf(monkeypatch):
    monkeypatch.setattr(CP, "_st", _stub_st)
    return CP.PrerequisiteClassifier()


def test_clf_fit_and_predict_roundtrip(clf):
    pairs = [("A", "B"), ("B", "C"), ("A", "C")]
    labels = [1, 0, 1]
    clf.fit(pairs, labels, balance="class_weight")
    probs = clf.predict_proba([("A", "B"), ("B", "C")])
    assert len(probs) == 2
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert clf.predict([("A", "B")], threshold=0.5) in ([0], [1])


def test_clf_fit_undersample_keeps_classifier_usable(clf):
    # heavily imbalanced: 2 positives, many negatives
    pairs = [("P%d" % i, "Q") for i in range(2)] + [("N%d" % i, "Q") for i in range(40)]
    labels = [1, 1] + [0] * 40
    clf.fit(pairs, labels, balance="undersample", max_neg_ratio=2, random_state=0)
    probs = clf.predict_proba([("P0", "Q"), ("N0", "Q")])
    assert len(probs) == 2


def test_clf_caches_embeddings(clf):
    pairs = [("A", "B"), ("A", "C")]
    labels = [1, 0]
    clf.fit(pairs, labels, balance="class_weight")
    cache_names = set(clf._vec_cache.keys())
    assert {"A", "B", "C"} <= cache_names


# ---------------------------------------------------------------------------
# llm_reasoning_check — second opinion (stubbed LLM)
# ---------------------------------------------------------------------------

def _fake_complete_returning(payload, backend="groq"):
    class _Result:
        def __init__(self):
            self.text = payload
            self._backend = backend
            self.cached = False

        @property
        def backend(self):
            return self._backend

    return lambda system, user, max_tokens, temperature: _Result()


def test_llm_reasoning_check_parses_json(monkeypatch):
    from backend.pipeline import llm
    monkeypatch.setattr(
        llm, "complete",
        _fake_complete_returning('{"prerequisite": true, "reason": "B builds on A"}'),
    )
    out = CP.llm_reasoning_check("A", "B", prediction=1, confidence=0.8)
    assert out["prediction"] is True
    assert out["reason"] == "B builds on A"
    assert out["backend"] == "groq"


def test_llm_reasoning_check_strips_code_fence(monkeypatch):
    from backend.pipeline import llm
    monkeypatch.setattr(
        llm, "complete",
        _fake_complete_returning('```json\n{"prerequisite":false,"reason":"no link"}\n```'),
    )
    out = CP.llm_reasoning_check("A", "B")
    assert out["prediction"] is False
    assert out["reason"] == "no link"


def test_llm_reasoning_check_handles_invalid_json(monkeypatch):
    from backend.pipeline import llm
    monkeypatch.setattr(
        llm, "complete",
        _fake_complete_returning("not json at all"),
    )
    out = CP.llm_reasoning_check("A", "B")
    assert out["prediction"] is None
    assert "not json" in out["reason"]


# ---------------------------------------------------------------------------
# classify_course_pairs — the Stage 4 bridge
# ---------------------------------------------------------------------------

def test_classify_course_pairs_empty_when_no_candidates(monkeypatch):
    monkeypatch.setattr(CP, "_st", _stub_st)
    monkeypatch.setattr(CP, "_load_lecturebank", lambda d: [("A", "B", 1)])
    # no candidate pairs -> short-circuits before any fitting
    monkeypatch.setattr(CP, "get_candidate_pairs", lambda concepts: [])
    out = CP.classify_course_pairs([{"name": "A"}, {"name": "B"}], lecturebank_dir="dir")
    assert out == []


def test_classify_course_pairs_raises_without_lecturebank(monkeypatch):
    monkeypatch.setattr(CP, "get_candidate_pairs", lambda concepts: [("A", "B")])
    monkeypatch.setattr(CP, "_load_lecturebank", lambda d: [])
    with pytest.raises(ValueError):
        CP.classify_course_pairs([{"name": "A"}, {"name": "B"}], lecturebank_dir="empty")


def test_classify_course_pairs_filters_below_threshold(monkeypatch):
    monkeypatch.setattr(CP, "_st", _stub_st)

    class _FixedClf:
        def __init__(self, *args, **kwargs):
            pass

        def fit(self, *a, **k):
            return self

        def predict_proba(self, pairs):
            return [0.95, 0.20]

    monkeypatch.setattr(CP, "PrerequisiteClassifier", _FixedClf)
    monkeypatch.setattr(CP, "get_candidate_pairs", lambda concepts: [("A", "B"), ("C", "D")])
    monkeypatch.setattr(CP, "_load_lecturebank", lambda d: [("X", "Y", 1)])

    out = CP.classify_course_pairs(
        [{"name": "A", "start_s": 0}, {"name": "B", "start_s": 1}],
        threshold=0.5, lecturebank_dir="d",
    )
    assert out == [{"a": "A", "b": "B", "confidence": 0.95}]
