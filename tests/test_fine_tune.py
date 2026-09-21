"""Unit tests for backend/pipeline/fine_tune.py (Phase 3 fine-tuning helpers).

Covers the pure/cheap logic (build_train_triples undersampling) and the
model-IO boundary (pair formatting, export/load round-trip, prediction shape)
against fakes — no weights are downloaded and no real training loops run here.
The actual transformer fine-tuning is exercised by scripts/kaggle_fine_tune.py
on GPU/CV and by smoke tests, not in this unit suite (too slow for CI).
"""

import numpy as np
import pytest

from backend.pipeline.fine_tune import _pair_text, build_train_triples


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


# ------------------------------------------------------------ model IO boundary

def test_pair_text_keeps_order_meaningful():
    assert _pair_text("Gradient Descent", "Loss Function") == (
        "Gradient Descent [SEP] Loss Function"
    )
    assert _pair_text("A", "B") != _pair_text("B", "A")


def test_export_model_saves_both_and_returns_dir(tmp_path):
    saved = []

    class FakeSaver:
        def save_pretrained(self, out_dir):
            saved.append((out_dir, type(self).__name__))

    out = tmp_path / "ckpt"
    from backend.pipeline import fine_tune as ft

    result = ft.export_model(FakeSaver(), FakeSaver(), str(out))
    assert result == str(out)
    assert saved == [(str(out), "FakeSaver"), (str(out), "FakeSaver")]


def test_load_model_reinstates_classifier_and_tokenizer(monkeypatch, tmp_path):
    from backend.pipeline import fine_tune as ft

    created = []

    class FakeModel:
        def __init__(self):
            self._device = None
            self._eval = False

        def to(self, device):
            self._device = device
            return self

        def eval(self):
            self._eval = True
            return self

    class FakeTokenizer:
        pass

    import transformers

    monkeypatch.setattr(
        transformers,
        "AutoModelForSequenceClassification",
        type("AM", (), {"from_pretrained": lambda *a, **k: FakeModel()}),
    )
    monkeypatch.setattr(
        transformers,
        "AutoTokenizer",
        type("AT", (), {"from_pretrained": lambda *a, **k: FakeTokenizer()}),
    )
    import torch

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    model, tok = ft.load_model(str(tmp_path))
    assert isinstance(model, FakeModel) and model._eval is True
    assert model._device == "cpu"
    assert isinstance(tok, FakeTokenizer)


def test_predict_pairs_returns_one_logit_per_pair(monkeypatch):
    import torch

    class FakeModel:
        def __init__(self):
            self._device = torch.device("cpu")
            self._calls = []

        def parameters(self):
            return iter([torch.nn.Parameter(torch.ones(1))])

        def __call__(self, **enc):
            self._calls.append(enc)

            class _Out:
                logits = torch.tensor([[0.5], [-1.0]])

            return _Out()

    class FakeTokenizer:
        def __call__(self, texts, **kw):
            n = len(texts)
            return {
                "input_ids": torch.zeros(n, 4, dtype=torch.long),
                "attention_mask": torch.ones(n, 4, dtype=torch.long),
            }

    from backend.pipeline import fine_tune as ft

    model = FakeModel()
    out = ft.predict_pairs(
        model, FakeTokenizer(), [("A", "B"), ("Gradient Descent", "Loss")]
    )
    assert out.shape == (2,)
    np.testing.assert_allclose(out, [0.5, -1.0], atol=1e-6)


def test_predict_pairs_single_pair_keeps_batch_dim():
    """SECURITY_AUDIT #20: a one-pair batch must not be double-unsqueezed.
    The tokenizer already returns a [1, seq] batch, so predict_pairs must pass
    it through unchanged (shape contract: one logit per pair)."""
    import torch

    class FakeModel:
        def __init__(self):
            self._calls = []

        def parameters(self):
            return iter([torch.nn.Parameter(torch.ones(1))])

        def __call__(self, **enc):
            self._calls.append(enc)

            class _Out:
                logits = torch.tensor([[0.7]])

            return _Out()

    class FakeTokenizer:
        def __call__(self, texts, **kw):
            return {
                "input_ids": torch.zeros(len(texts), 4, dtype=torch.long),
                "attention_mask": torch.ones(len(texts), 4, dtype=torch.long),
            }

    from backend.pipeline import fine_tune as ft

    model = FakeModel()
    out = ft.predict_pairs(model, FakeTokenizer(), [("A", "B")])
    assert out.shape == (1,)
    np.testing.assert_allclose(out, [0.7], atol=1e-6)
    assert model._calls[0]["input_ids"].shape == (1, 4)  # batch dim untouched


def test_validate_model_dir_rejects_unsafe_paths(tmp_path, monkeypatch):
    """SECURITY_AUDIT #21: traversal and non-directories are refused, and an
    optional trusted-roots allowlist is enforced."""
    from backend.pipeline import fine_tune as ft

    good = tmp_path / "ckpt"
    good.mkdir()
    assert ft._validate_model_dir(str(good)) == str(good.resolve())

    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    with pytest.raises(ValueError):
        ft._validate_model_dir(str(file_path))  # not a directory
    with pytest.raises(ValueError):
        ft._validate_model_dir(str(tmp_path / ".." / "escape"))
    with pytest.raises(ValueError):
        ft._validate_model_dir("")

    # trusted-roots allowlist
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("LECGAP_MODEL_ROOTS", str(good))
    with pytest.raises(ValueError):
        ft._validate_model_dir(str(other))
    assert ft._validate_model_dir(str(good))
