"""
Stage 3 — Prerequisite Classification (the project's technical core)
See plan/ARCHITECTURE.md, Stage 3, and plan/EVALUATION.md.

For candidate concept pairs (A, B): does A need to be understood before B?

  get_candidate_pairs(concepts)  -> pre-filters which pairs are even worth
                                    checking (close in time, or semantically
                                    similar via embeddings) — NOT exhaustive
                                    (avoids pair explosion, see ARCHITECTURE).

  classify_pairs(pairs, model)   -> fine-tuned classifier's predictions +
                                    confidences for a list of (A, B) pairs.

  llm_reasoning_check(a, b)      -> second-opinion LLM pass that also produces
                                    a human-readable explanation (reused in the
                                    faculty dashboard later).

Design notes (see EVALUATION.md):
  * Fine-tune a pretrained embedding model, do NOT train from scratch.
  * Positive class is heavily imbalanced (~2% of pairs) -> oversample.
  * Cross-validate rather than a single train/test split.
  * Report precision / recall / F1.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import os
import threading

import numpy as np

from backend.pipeline.model_ids import EMBEDDING_MODEL, load_kwargs

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _st():
    """Lazy-load sentence_transformers (torch ≈ 35–60 s cold) only when the
    encoder is actually needed — keeps API boot and pure test paths fast."""
    from sentence_transformers import SentenceTransformer, util

    return SentenceTransformer, util


def get_candidate_pairs(
    concepts: List[Dict],
    *,
    time_window_s: float = 120.0,
    sim_threshold: float = 0.6,
    encoder=None,
) -> List[Tuple[str, str]]:
    """
    Return candidate (prerequisite, target) name pairs worth classifying.

    Pre-filter rules (avoid exhaustive n^2):
      1. Semantic proximity: two concepts named in the SAME or nearby time
         window of a lecture are candidates.
      2. Embedding similarity: concepts that are semantically related
         (cosine >= sim_threshold) are candidates even if far apart in time.

    `encoder` is an optional already-loaded SentenceTransformer; pass the one
    PrerequisiteClassifier/graph builder are using so the weights load once
    per process instead of once per stage.
    """
    candidates: List[Tuple[str, str]] = []
    seen = set()

    # 1. Temporal proximity: same lecture chunk / overlapping time window.
    for a in concepts:
        for b in concepts:
            if a["name"] == b["name"]:
                continue
            if a.get("start_s") is None or b.get("start_s") is None:
                continue
            if abs(a["start_s"] - b["start_s"]) <= time_window_s:
                key = (a["name"], b["name"])
                if key not in seen:
                    seen.add(key)
                    candidates.append((a["name"], b["name"]))

    # 2. Embedding similarity (across everything, incl. far-apart concepts).
    #    Vectorized (M8): L2-normalise once and take one pairwise matmul
    #    instead of O(n^2) fresh numpy allocations, so the threshold test is a
    #    plain matrix lookup per pair.
    if encoder is None:
        SentenceTransformer, _ = _st()
        encoder = SentenceTransformer(EMBEDDING_MODEL, **load_kwargs(EMBEDDING_MODEL))
    names = [c["name"] for c in concepts]
    mat = np.asarray(encoder.encode(names, convert_to_tensor=False), dtype=np.float32)
    row_norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat_n = mat / np.maximum(row_norms, 1e-8)
    sim = mat_n @ mat_n.T
    for i in range(len(names)):
        for j in range(len(names)):
            if i == j:
                continue
            if sim[i, j] >= sim_threshold:
                key = (names[i], names[j])
                if key not in seen:
                    seen.add(key)
                    candidates.append((names[i], names[j]))

    return candidates


def _pair_features(pairs, cached_vecs: Dict[str, np.ndarray], *, interactions: bool = True) -> np.ndarray:
    """Assemble concatenated (A, B) feature vectors via a name->vec cache.

    Returns an (n, 2*d [+ i]) numpy array where the optional interaction
    block adds the element-wise difference |A-B|, element-wise product A*B,
    and the cosine similarity — cheap asymmetry/asociation signals a linear
    head can use to answer 'does A precede B?' without a cross-attention net.
    """
    names = sorted(set(n for pair in pairs for n in pair))
    index = {n: i for i, n in enumerate(names)}
    mat = np.stack([cached_vecs[n] for n in names])
    la, lb = [], []
    for a, b in pairs:
        la.append(index[a])
        lb.append(index[b])
    A = mat[la]
    B = mat[lb]
    cols = [A, B]
    if interactions:
        cols.append(np.abs(A - B))
        cols.append(A * B)
        norm = np.linalg.norm(A, axis=1, keepdims=True) * np.linalg.norm(B, axis=1, keepdims=True)
        cols.append((A * B).sum(axis=1, keepdims=True) / np.maximum(norm, 1e-8))
    return np.concatenate(cols, axis=1)


class PrerequisiteClassifier:
    """Binary prerequisite classifier built on top of a frozen pretrained
    embedding model, with a fine-tuned logistic/MLP head.

    Matches 'fine-tune a pretrained embedding model' intent: the encoder is
    pretrained (all-MiniLM-L6-v2) and the learned head is trained on LectureBank
    labeled pairs, with class oversampling to counter the ~2% positive rate.
    """

    def __init__(
        self,
        embedding_model: str = EMBEDDING_MODEL,
        *,
        encoder=None,
    ):
        self.embedding_model = embedding_model
        self._encoder = encoder
        self._vec_cache: Dict[str, np.ndarray] = {}
        self._head = None
        self._interactions: bool = True

    def _get_encoder(self):
        if self._encoder is None:
            SentenceTransformer, _util = _st()
            self._encoder = SentenceTransformer(
                self.embedding_model, **load_kwargs(self.embedding_model)
            )
        return self._encoder

    def _vectors_for(self, names) -> Dict[str, np.ndarray]:
        """Return (and cache) embeddings for the given unique names."""
        names = set(names)
        missing = [n for n in names if n not in self._vec_cache]
        if missing:
            enc = self._get_encoder()
            vecs = enc.encode(missing, convert_to_tensor=False)
            for n, v in zip(missing, vecs):
                self._vec_cache[n] = np.asarray(v, dtype=np.float32)
        return self._vec_cache

    def fit(
        self,
        pairs,
        labels,
        *,
        balance: str = "undersample",
        max_neg_ratio: Optional[float] = 16,
        interactions: bool = True,
        random_state: Optional[int] = None,
    ) -> "PrerequisiteClassifier":
        """Train the logistic head.

        Imbalance handling (positive class is ~2% in LectureBank):
          balance="class_weight"  -> sklearn weights classes inversely to
                                     their frequency. Cheap and statistically
                                     sound; the default.
          balance="undersample"   -> downsample negatives to a fixed ratio so
                                     the training set stays small (fast on CPU).
        When balance="undersample", max_neg_ratio caps negatives/positives
        (e.g. 4 -> at most 4 negatives per positive).
        """
        from sklearn.linear_model import LogisticRegression

        self._interactions = interactions
        pair_list = list(pairs)
        cache = self._vectors_for([n for pair in pair_list for n in pair])
        X = _pair_features(pair_list, cache, interactions=interactions)
        y = np.asarray(list(labels))

        if balance == "undersample":
            pos_idx = np.where(y == 1)[0]
            neg_idx = np.where(y == 0)[0]
            ratio = max_neg_ratio if max_neg_ratio else max(1, int(neg_idx.size / max(1, pos_idx.size)))
            keep_neg = np.random.RandomState(random_state).choice(
                neg_idx, size=pos_idx.size * ratio, replace=False
            )
            sel = np.concatenate([pos_idx, keep_neg])
            X, y = X[sel], y[sel]

        model = LogisticRegression(
            max_iter=2000,
            class_weight="balanced" if balance == "class_weight" else None,
        )
        model.fit(X, y)
        self._head = model
        return self

    def predict_proba(self, pairs: Sequence[Tuple[str, str]]) -> List[float]:
        pair_list = list(pairs)
        cache = self._vectors_for([n for pair in pair_list for n in pair])
        X = _pair_features(pair_list, cache, interactions=self._interactions)
        return [float(p[1]) for p in self._head.predict_proba(X)]

    def predict(self, pairs: Sequence[Tuple[str, str]], threshold: float = 0.5) -> List[int]:
        return [1 if p >= threshold else 0 for p in self.predict_proba(pairs)]


# How much a "not a prerequisite" LLM verdict demotes a classifier edge. The
# edge survives (the LLM is one fallible signal among several) but ranks below
# an uncontested one in cycle resolution and learner ordering.
VETO_CONFIDENCE_FACTOR = 0.4


def _coerce_confidence(value) -> Optional[float]:
    """Parse an LLM's self-reported confidence to [0, 1]; None when absent."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def llm_reasoning_check(
    a: str,
    b: str,
    *,
    prediction: Optional[int] = None,
    confidence: Optional[float] = None,
) -> Dict:
    """
    Second-opinion LLM pass: does 'a' need to be understood before 'b'?

    Returns the LLM verdict, an optional self-reported confidence, a
    human-readable explanation, and — crucially — ``adjusted_confidence``: the
    input classifier confidence modulated by the verdict rather than vetoed by
    it (M1). A raw "no" from a fallible, prompt-injectable model must not
    silently delete a learned edge, so a rejection demotes the edge's weight
    (``VETO_CONFIDENCE_FACTOR``) and lets cycle resolution / learner ordering
    rank it down; an affirmation or an unparseable verdict leaves the prior
    confidence untouched. Concept names are lecture-derived untrusted data and
    are delimited accordingly.
    """
    from backend.pipeline.llm import complete
    from backend.pipeline.prompt_guard import DATA_GUARD, delimit_untrusted

    context = ""
    if prediction is not None:
        context = (
            f"\nFor reference, a previous model predicted "
            f"{'YES' if prediction == 1 else 'NO'} with confidence "
            f"{confidence:.2f}."
        )
    system = (
        "You determine whether a concept A is a prerequisite of concept B "
        "(A must be understood before B). Reply with JSON only: "
        '{"prerequisite": true|false, "reason": "short explanation", '
        '"confidence": <float 0..1, how sure you are>}. ' + DATA_GUARD
    )
    user = (
        f"Concept A: {delimit_untrusted(str(a))}\n"
        f"Concept B: {delimit_untrusted(str(b))}\n"
        f"Is A a prerequisite of B?{context}"
    )
    result = complete(system, user, max_tokens=200, temperature=0.0)

    import json
    import re

    text = re.sub(r"```(?:json)?\s*|\s*```", "", result.text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"prerequisite": None, "reason": result.text[:300]}

    verdict = data.get("prerequisite")
    base = float(confidence) if confidence is not None else 0.5
    adjusted = base if verdict is not False else base * VETO_CONFIDENCE_FACTOR

    return {
        "prediction": verdict,
        "confidence": _coerce_confidence(data.get("confidence")),
        "adjusted_confidence": max(0.0, min(1.0, adjusted)),
        "reason": data.get("reason", ""),
        "backend": result.backend,
        "cached": result.cached,
    }


# ---------------------------------------------------------------------------
# lecturebank load + shared fitted classifier (H4)
# ---------------------------------------------------------------------------
_lecturebank_lock = threading.Lock()
_lecturebank_cache: Dict[str, List[Tuple[str, str, int]]] = {}
_fitted_cache_lock = threading.Lock()
_fitted_cache: Dict[tuple, "_CachedFit"] = {}


class _CachedFit:
    """Cache entry that ALSO pins strong refs to ``lib``/``encoder`` so an
    ``id()`` can never be silently recycled by a different object (which would
    make the cache return a stale fit to an unrelated caller)."""

    __slots__ = ("lib", "encoder", "clf")

    def __init__(self, lib, encoder, clf):
        self.lib = lib
        self.encoder = encoder
        self.clf = clf


def _load_lecturebank(lecturebank_dir) -> List[Tuple[str, str, int]]:
    """(name_a, name_b, label) triples from data/lecturebank (see evaluate_classifier).

    Memoized per directory (H4): the CSVs are static for the process, so every
    course-graph rebuild reusing the same directory skips the file read. Tests
    monkeypatch this function directly, which bypasses the memo entirely.
    """
    key = os.path.abspath(lecturebank_dir)
    with _lecturebank_lock:
        if key in _lecturebank_cache:
            return _lecturebank_cache[key]

    import csv

    name_of = {}
    topics_file = os.path.join(lecturebank_dir, "208topics.csv")
    if os.path.exists(topics_file):
        with open(topics_file, newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    name_of[row[0]] = row[1]

    pairs: List[Tuple[str, str, int]] = []
    annot_file = os.path.join(lecturebank_dir, "prerequisite_annotation.csv")
    if os.path.exists(annot_file):
        with open(annot_file, newline="", encoding="utf-8") as f:
            for src, tgt, label in csv.reader(f):
                if src in name_of and tgt in name_of:
                    pairs.append((name_of[src], name_of[tgt], int(label)))
    with _lecturebank_lock:
        _lecturebank_cache[key] = pairs
    return pairs


def _fitted_classifier(
    lib: Sequence[Tuple[str, str, int]],
    *,
    encoder=None,
) -> "PrerequisiteClassifier":
    """Return a LectureBank-fitted classifier, cached across calls (H4).

    Course-graph rebuilds no longer re-fit the logistic head on the full
    LectureBank per lecture. The cache key is the *identity* of the loaded
    training-trip list and the encoder object, and each entry pins strong refs
    to both so an ``id()`` cannot be recycled by an unrelated object:
      - production: `_load_lecturebank` returns one memoized list object and
        the shared encoder is stable -> one fit per process, reused forever;
      - tests: monkeypatched loads/fakes produce fresh objects per call -> no
        cross-test cache bleeding.
    """
    key = (id(lib), id(encoder))
    with _fitted_cache_lock:
        entry = _fitted_cache.get(key)
        if entry is not None and entry.lib is lib and entry.encoder is encoder:
            return entry.clf
        clf = PrerequisiteClassifier(encoder=encoder).fit(
            [(a, b) for a, b, _ in lib],
            [lbl for _, _, lbl in lib],
            balance="undersample",
            max_neg_ratio=16,
        )
        _fitted_cache[key] = _CachedFit(lib, encoder, clf)
        return clf


def classify_course_pairs(
    concepts: List[Dict],
    *,
    threshold: float = 0.5,
    lecturebank_dir: Optional[str] = None,
    encoder=None,
) -> List[Dict]:
    """Course-scoped bridge into Stage 4 (graph construction).

    Takes a course's extracted concepts, generates candidate (A, B) pairs
    with get_candidate_pairs, and scores them with a PrerequisiteClassifier
    fitted on LectureBank (same recipe as the Phase 3 evaluation).

    `encoder` is an optional shared SentenceTransformer; when given, the same
    loaded weights serve candidate pre-filtering, fitting, and prediction (one
    "Loading weights" line per process instead of three).

    Returns confirmed pairs as [{"a": name, "b": name, "confidence": p}] for
    p >= threshold, ready for build_graph.add_edge.
    """
    if lecturebank_dir is None:
        lecturebank_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "lecturebank"
        )
    lib = _load_lecturebank(lecturebank_dir)
    if not lib:
        raise ValueError(
            f"No LectureBank data at {lecturebank_dir}; prerequisite edges "
            "cannot be learned without it."
        )

    candidates = get_candidate_pairs(concepts, encoder=encoder)
    if not candidates:
        return []

    clf = _fitted_classifier(lib, encoder=encoder)
    probs = clf.predict_proba(candidates)
    return [
        {"a": a, "b": b, "confidence": float(p)}
        for (a, b), p in zip(candidates, probs)
        if p >= threshold
    ]
