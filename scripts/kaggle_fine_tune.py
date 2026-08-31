"""
Phase 3 — fine-tune the encoder and evaluate 5-fold CV, GPU-or-CPU agnostic.

This is the training+benchmark counterpart to evaluate_classifier.py (which
scores the frozen-encoder baseline). It fine-tunes a cross-encoder transformer
over LectureBank pairs and reports precision/recall/F1 with the SAME nested
threshold-selection methodology (threshold picked on a held-out val slice,
never the test fold).

Runs identically on:
  * Local CPU:  & D:\\Anaconda3\\envs\\lecgap\\python.exe scripts/kaggle_fine_tune.py --epochs 1
  * Kaggle GPU: python scripts/kaggle_fine_tune.py --input-dir /kaggle/input/datasets/ayushdevadiga/lecturebank \\
                   --output-dir /kaggle/working --epochs 3

CSVs expected (upload as a Kaggle dataset under your account — adjust the
input-dir if your dataset slug differs):
  prerequisite_annotation.csv :: (Source_Topic_ID, Target_Topic_ID, If_prerequisite)
  208topics.csv               :: (id, Topic, Topic_Link)

Export: the model fine-tuned on ALL data is written to <output-dir>/model/ for
download and CPU inference in the main pipeline.
"""

import argparse
import csv
import os
import sys

from collections import Counter

import numpy as np

from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.pipeline.fine_tune import (
    build_train_triples,
    export_model,
    fine_tune_cross_encoder,
    predict_pairs,
)


def load_data(annot_file, topics_file):
    name_of = {}
    with open(topics_file, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                name_of[row[0]] = row[1]
    pairs = []
    with open(annot_file, newline="", encoding="utf-8") as f:
        for src, tgt, label in csv.reader(f):
            if src in name_of and tgt in name_of:
                pairs.append((name_of[src], name_of[tgt], int(label)))
    return name_of, pairs


def run_cv(X, y, *, max_neg_ratio, epochs, batch_size, lr, device):
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    metrics = []
    for fold, (tr_idx, te_idx) in enumerate(skf.split(X, y)):
        tr_idx = list(tr_idx)
        vskf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
        fit_idx, val_idx = next(iter(vskf.split(tr_idx, [y[i] for i in tr_idx])))
        fit_idx = [tr_idx[i] for i in fit_idx]
        val_idx = [tr_idx[i] for i in val_idx]

        tr_pairs = [X[i] for i in fit_idx]
        tr_labels = [y[i] for i in fit_idx]
        va_pairs = [X[i] for i in val_idx]
        va_labels = [y[i] for i in val_idx]
        te_pairs = [X[i] for i in te_idx]
        te_labels = [y[i] for i in te_idx]

        triples = build_train_triples(tr_pairs, tr_labels, max_neg_ratio=max_neg_ratio)
        model, tok = fine_tune_cross_encoder(
            triples,
            epochs=epochs,
            batch_size=batch_size,
            lr=lr,
            device=device,
        )

        va_logits = predict_pairs(model, tok, va_pairs)
        best = (0.0, 0.0)
        for t in np.arange(-2.0, 3.0, 0.1):
            preds = [1 if s >= t else 0 for s in va_logits]
            f = f1_score(va_labels, preds, zero_division=0)
            if f > best[0]:
                best = (f, float(t))
        thr = best[1]

        te_logits = predict_pairs(model, tok, te_pairs)
        preds = [1 if s >= thr else 0 for s in te_logits]
        m = {
            "p": precision_score(te_labels, preds, zero_division=0),
            "r": recall_score(te_labels, preds, zero_division=0),
            "f1": f1_score(te_labels, preds, zero_division=0),
            "acc": sum(p == t for p, t in zip(preds, te_labels)) / len(te_labels),
            "thr": thr,
        }
        metrics.append(m)
        print(
            f"  fold {fold+1}: P={m['p']:.3f} R={m['r']:.3f} "
            f"F1={m['f1']:.3f} acc={m['acc']:.3f} @thr={thr:.2f}",
            flush=True,
        )
    n = len(metrics)
    print("\n=== 5-fold CV (fine-tuned) summary ===")
    print(f"Precision (avg): {sum(m['p'] for m in metrics) / n:.3f}")
    print(f"Recall    (avg): {sum(m['r'] for m in metrics) / n:.3f}")
    print(f"F1        (avg): {sum(m['f1'] for m in metrics) / n:.3f}")
    print(f"Accuracy  (avg): {sum(m['acc'] for m in metrics) / n:.3f}")
    return sum(m["f1"] for m in metrics) / n


def _resolve_input_dir(input_dir: str) -> str:
    """Return a directory containing both lecturebank CSVs.

    If ``input_dir`` already holds them, use it as-is. Otherwise, on Kaggle,
    scan the standard input roots for the two CSVs (the dataset slug is not
    always predictable — e.g. /kaggle/input/datasets/<user>/<slug>/).
    """
    def present(d):
        return os.path.isfile(os.path.join(d, "prerequisite_annotation.csv")) and \
            os.path.isfile(os.path.join(d, "208topics.csv"))

    if present(input_dir):
        return input_dir

    roots = []
    if os.path.isdir("/kaggle/input"):
        roots.append("/kaggle/input")
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            if "prerequisite_annotation.csv" in filenames and "208topics.csv" in filenames:
                print(f"Found lecturebank data at {dirpath}", flush=True)
                return dirpath
    return input_dir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="data/lecturebank")
    ap.add_argument("--output-dir", default="data/lecturebank/model")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-neg-ratio", type=int, default=8)
    ap.add_argument("--device", default=None)
    args = ap.parse_args()

    input_dir = _resolve_input_dir(args.input_dir)
    annot = os.path.join(input_dir, "prerequisite_annotation.csv")
    topics = os.path.join(input_dir, "208topics.csv")
    name_of, pairs = load_data(annot, topics)
    X = [(a, b) for a, b, _ in pairs]
    y = [l for _, _, l in pairs]
    print(f"Loaded {len(pairs)} pairs across {len(name_of)} topics; "
          f"balance {Counter(y)}", flush=True)

    run_cv(
        X, y,
        max_neg_ratio=args.max_neg_ratio,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        device=args.device,
    )

    # Final model on ALL data for deployment.
    print("\nFine-tuning final model on all data...", flush=True)
    triples = build_train_triples(X, y, max_neg_ratio=args.max_neg_ratio)
    model, tok = fine_tune_cross_encoder(
        triples, epochs=args.epochs, batch_size=args.batch_size,
        lr=args.lr, device=args.device,
    )
    out = export_model(model, tok, args.output_dir)
    print(f"Exported fine-tuned model to {out}", flush=True)


if __name__ == "__main__":
    main()
