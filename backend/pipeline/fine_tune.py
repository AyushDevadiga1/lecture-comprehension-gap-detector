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

import numpy as np

_DEF_BASE = "sentence-transformers/all-MiniLM-L6-v2"


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

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    # Convert the ST/MPNet checkpoint into a binary sequence-classification
    # head, keeping its pretrained weights (they are loaded as the base).
    config = AutoConfig.from_pretrained(base_model, num_labels=1)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, config=config, ignore_mismatched_sizes=True
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
    seed: int = 42,
    device: str = None,
):
    """Fine-tune a (cross-encoder) transformer on (a, b, label) triples.

    Returns (model, tokenizer) with the trained weights. The full network
    (transformer body + classification head) is trained — this is the
    "fine-tune, don't train from scratch" step the plan calls for.
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

    optimizer = AdamW(model.parameters(), lr=lr)
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


def load_model(model_dir: str, device: str = None):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

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
    if len(texts) == 1:
        for k in enc:
            enc[k] = enc[k].unsqueeze(0)
    with torch.no_grad():
        logits = model(**enc).logits
    return logits.squeeze(-1).detach().cpu().numpy()
