"""
Phase 3 — fine-tuning the pretrained encoder on LectureBank pairs.

Builds on the frozen-encoder baseline (classify_prerequisites.py) by actually
training the transformer over labeled (A, B) pairs, per plan/EVALUATION.md
"fine-tune a pretrained embedding model (not train from scratch)".

Design:
  * Cross-encoder style: loads the MiniLM checkpoint and adds a binary
    sequence-classification head, then fine-tunes ALL weights over the pairs.
    This is trained with a plain PyTorch loop (no trainer/datasets coupling) so
    the exact same code runs locally on CPU and on Kaggle GPU.
  * Paired texts are fed as "[A] [SEP] [B]" so the model attends jointly, i.e.
    it can answer "is A a prerequisite of B?" — the ordering matters and the
    model sees it.
  * Deterministic seed for reproducible CV.
"""

from typing import List, Optional, Sequence, Tuple

import os
from pathlib import Path

import numpy as np

from backend.pipeline.model_ids import EMBEDDING_MODEL, load_kwargs

# Keep the transformers LOAD REPORT (UNEXPECTED / MISSING keys emitted when loading
# a sentence-encoder checkpoint into a sequence-classification head) out of the log.
# The MISSING classifier weights are intentionally freshly-initialized head params
# and the UNEXPECTED position_ids are a benign task-shape mismatch — both expected.
import logging as _logging
import transformers as _transformers

_transformers.logging.set_verbosity_error()
_logging.getLogger("transformers").setLevel(_logging.ERROR)

# L10: the fine-tune base mirrors the pinned runtime encoder (env-overridable).
_DEF_BASE = EMBEDDING_MODEL


def build_train_triples(
    pairs: Sequence[Tuple[str, str]],
    labels: Sequence[int],
    *,
    max_neg_ratio: int = 8,
    random_state: Optional[int] = None,
) -> List[Tuple[str, str, int]]:
    """Undersample negatives to max_neg_ratio:1 vs positives.

    Returns [(text_a, text_b, label), ...] ready for training.
    """
    pos = [(p[0], p[1], 1) for p, l in zip(pairs, labels) if l == 1]
    neg = [(p[0], p[1], 0) for p, l in zip(pairs, labels) if l == 0]
    import random as _random

    rng = _random.Random(random_state)
    neg = rng.sample(neg, min(len(neg), len(pos) * max_neg_ratio))
    all_ = pos + neg
    rng.shuffle(all_)
    return all_


def _pair_text(a: str, b: str) -> str:
    """Format a pair for the cross-encoder. Order is meaningful (A precedes B)."""
    return f"{a} [SEP] {b}"


def _build_model(base_model: str, device: str):
    import torch
    from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model, **load_kwargs(base_model))
    # Convert the ST/MPNet checkpoint into a binary sequence-classification
    # head, keeping its pretrained weights (they are loaded as the base).
    config = AutoConfig.from_pretrained(base_model, num_labels=1)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, config=config, ignore_mismatched_sizes=True, **load_kwargs(base_model)
    )
    model.to(device)
    return model, tokenizer


def fine_tune_cross_encoder(
    train_triples: Sequence[Tuple[str, str, int]],
    *,
    base_model: str = _DEF_BASE,
    val_triples: Optional[Sequence[Tuple[str, str, int]]] = None,
    epochs: int = 3,
    batch_size: int = 32,
    lr: float = 2e-5,
    weight_decay: float = 0.0,
    grad_clip: Optional[float] = None,
    seed: int = 42,
    device: str = None,
):
    """Fine-tune a (cross-encoder) transformer on (a, b, label) triples.

    Returns (model, tokenizer) with the trained weights. The full network
    (transformer body + classification head) is trained — this is the
    "fine-tune, don't train from scratch" step the plan calls for.
    ``weight_decay`` (L2 on non-bias/norm params, per common practice) and
    ``grad_clip`` (max gradient norm) help fight the overfitting/instability
    seen on the small LectureBank positive pool.
    """
    import torch
    from torch.utils.data import DataLoader, TensorDataset
    from torch.optim import AdamW
    from torch.nn import BCEWithLogitsLoss

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    torch.manual_seed(seed)
    np.random.seed(seed)

    model, tokenizer = _build_model(base_model, device)

    # Encode all texts once.
    texts = [ _pair_text(a, b) for a, b, _ in train_triples ]
    enc = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=128,
        return_tensors="pt",
    )
    labels = torch.tensor([float(l) for _, _, l in train_triples], dtype=torch.float)
    dataset = TensorDataset(enc["input_ids"], enc["attention_mask"], labels)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # Apply weight decay only to 2D (weight) params, not biases/norms — standard.
    decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
    no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]
    optimizer = AdamW(
        [
            {"params": decay, "weight_decay": weight_decay},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=lr,
    )
    loss_fn = BCEWithLogitsLoss()

    model.train()
    for epoch in range(epochs):
        total = 0.0
        for step, (ids, mask, lbl) in enumerate(loader):
            ids, mask, lbl = ids.to(device), mask.to(device), lbl.to(device)
            optimizer.zero_grad()
            logits = model(input_ids=ids, attention_mask=mask, labels=None).logits
            loss = loss_fn(logits.squeeze(-1), lbl)
            loss.backward()
            if grad_clip is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
            optimizer.step()
            total += loss.item()
        avg = total / max(1, len(loader))
        # (val logging intentionally omitted — eval is done by evaluate_classifier.)

    return model, tokenizer


def export_model(model, tokenizer, output_dir: str) -> str:
    """Save the fine-tuned transformer + tokenizer; return the path."""
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    return output_dir


def _validate_model_dir(model_dir: str) -> str:
    """Validate a model directory before handing it to transformers (#21).

    Rejects NUL bytes and ``..`` traversal, requires an existing directory, and
    — when ``LECGAP_MODEL_ROOTS`` is set (os.pathsep-separated) — requires the
    resolved directory to live under one of those trusted roots.
    """
    raw = str(model_dir).strip()
    if not raw or "\x00" in raw:
        raise ValueError("model_dir must be a non-empty path")
    p = Path(raw)
    if ".." in p.parts:
        raise ValueError(f"model_dir must not contain '..': {model_dir!r}")
    resolved = p.resolve()
    if not resolved.is_dir():
        raise ValueError(f"model_dir is not a directory: {model_dir!r}")
    roots = os.getenv("LECGAP_MODEL_ROOTS", "").strip()
    if roots:
        allowed = [Path(r).resolve() for r in roots.split(os.pathsep) if r.strip()]
        if not any(resolved == root or root in resolved.parents for root in allowed):
            raise ValueError(f"model_dir outside LECGAP_MODEL_ROOTS: {model_dir!r}")
    return str(resolved)


def load_model(model_dir: str, device: str = None):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_dir = _validate_model_dir(model_dir)
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model.to(device)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    return model, tokenizer


def predict_pairs(model, tokenizer, pairs: Sequence[Tuple[str, str]]) -> np.ndarray:
    """Return a per-pair logit; higher = A is more likely a prereq of B."""
    import torch

    texts = [_pair_text(a, b) for a, b in pairs]
    enc = tokenizer(texts, padding=True, truncation=True, max_length=128, return_tensors="pt")
    device = next(model.parameters()).device
    enc = {k: v.to(device) for k, v in enc.items()}
    with torch.no_grad():
        logits = model(**enc).logits
    return logits.squeeze(-1).detach().cpu().numpy()
