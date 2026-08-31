"""Unit tests for backend/pipeline/fine_tune.py (Phase 3 fine-tuning helpers).

Only pure/cheap logic is tested here — build_train_triples (undersampling).
The actual transformer fine-tuning is exercised by scripts/kaggle_fine_tune.py
on GPU/CV and by smoke tests, not in this unit suite (too slow for CI).
"""

import numpy as np

from backend.pipeline.fine_tune import build_train_triples


def test_build_train_triples_undersamples_negatives():
    pairs = [("a", "b"), ("c", "d"), ("e", "f")]
    labels = [1, 0, 0]  # 1 positive, 2 negative
    triples = build_train_triples(pairs, labels, max_neg_ratio=1, random_state=0)
    # max 1 negative per positive
    assert sum(l for _, _, l in triples) == 1
    assert len([t for t in triples if t[2] == 0]) <= 1


def test_build_train_triples_keeps_all_positives():
    pairs = [("a", "b"), ("c", "d"), ("e", "f"), ("g", "h")]
    labels = [1, 1, 0, 0]
    triples = build_train_triples(pairs, labels, max_neg_ratio=8, random_state=0)
    n_pos = sum(l for _, _, l in triples)
    assert n_pos == 2
    assert len(triples) == 4  # both negatives kept (2 neg <= 2*8)


def test_build_train_triples_deterministic():
    pairs = [(str(i), str(i + 1)) for i in range(20)]
    labels = [1 if i % 5 == 0 else 0 for i in range(20)]
    a = build_train_triples(pairs, labels, max_neg_ratio=2, random_state=42)
    b = build_train_triples(pairs, labels, max_neg_ratio=2, random_state=42)
    assert [(x, y, z) for x, y, z in a] == [(x, y, z) for x, y, z in b]


def test_build_train_triples_empty_negative_only():
    pairs = [("a", "b"), ("c", "d")]
    labels = [0, 0]
    triples = build_train_triples(pairs, labels, max_neg_ratio=1, random_state=0)
    assert sum(l for _, _, l in triples) == 0
    assert len([t for t in triples if t[2] == 0]) == 0
