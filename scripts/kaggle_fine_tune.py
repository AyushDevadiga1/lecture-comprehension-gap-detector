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
import json
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


def run_cv(X, y, *, max_neg_ratio, epochs, batch_size, lr, base_model, weight_decay, grad_clip, device):
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
            base_model=base_model,
            weight_decay=weight_decay,
            grad_clip=grad_clip,
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
    avgs = {
        "p": sum(m["p"] for m in metrics) / n,
        "r": sum(m["r"] for m in metrics) / n,
        "f1": sum(m["f1"] for m in metrics) / n,
        "acc": sum(m["acc"] for m in metrics) / n,
    }
    print("\n=== 5-fold CV (fine-tuned) summary ===")
    print(f"Precision (avg): {avgs['p']:.3f}")
    print(f"Recall    (avg): {avgs['r']:.3f}")
    print(f"F1        (avg): {avgs['f1']:.3f}")
    print(f"Accuracy  (avg): {avgs['acc']:.3f}")
    return {"avgs": avgs, "folds": metrics}


def _train_val_test_split(X, y, random_state=42):
    """Return (train_pairs, train_labels, val_pairs, val_labels, test_pairs, test_labels)
    from a single stratified split — used for fast hyperparameter selection."""
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
    tr_idx, te_idx = next(iter(skf.split(X, y)))
    tr_idx = list(tr_idx)
    vskf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    fit_idx, val_idx = next(iter(vskf.split(tr_idx, [y[i] for i in tr_idx])))
    fit_idx = [tr_idx[i] for i in fit_idx]
    val_idx = [tr_idx[i] for i in val_idx]
    return (
        [X[i] for i in fit_idx], [y[i] for i in fit_idx],
        [X[i] for i in val_idx], [y[i] for i in val_idx],
        [X[i] for i in te_idx], [y[i] for i in te_idx],
    )


def tune_hyperparams(X, y, *, epochs_grid, lr_grid, ratio_grid, batch_size, base_model, weight_decay, grad_clip, device):
    """Single-split hyperparameter sweep over a small grid.

    Returns the best (epochs, lr, max_neg_ratio) by val-F1. Fast on GPU —
    each config trains once on the fit slice. The test slice is never touched
    during selection, so the eventual 5-fold CV remains fair.
    """
    tr_pairs, tr_labels, va_pairs, va_labels, _te_pairs, _te_labels = _train_val_test_split(X, y)
    results = []
    for e in epochs_grid:
        for lr in lr_grid:
            for ratio in ratio_grid:
                triples = build_train_triples(tr_pairs, tr_labels, max_neg_ratio=ratio)
                model, tok = fine_tune_cross_encoder(
                    triples, epochs=e, batch_size=batch_size, lr=lr,
                    base_model=base_model, weight_decay=weight_decay,
                    grad_clip=grad_clip, device=device,
                )
                va_logits = predict_pairs(model, tok, va_pairs)
                best_f, best_t = (0.0, 0.0)
                for t in np.arange(-2.0, 3.0, 0.1):
                    preds = [1 if s >= t else 0 for s in va_logits]
                    f = f1_score(va_labels, preds, zero_division=0)
                    if f > best_f:
                        best_f, best_t = f, float(t)
                results.append((best_f, e, lr, ratio, best_t))
                print(f"  tune e={e} lr={lr} ratio={ratio}: val-F1={best_f:.3f} @thr={best_t:.2f}",
                      flush=True)
    results.sort(key=lambda r: -r[0])
    best_f, e, lr, ratio, t = results[0]
    print("\n=== Best hyperparams (by val-F1) ===")
    print(f"epochs={e}, lr={lr}, max_neg_ratio={ratio}  (val-F1 {best_f:.3f} @thr={t:.2f})")
    return e, lr, ratio



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
    ap.add_argument("--base-model", default=None,
                    help="HF model id to fine-tune from (default fine_tune._DEF_BASE)")
    ap.add_argument("--weight-decay", type=float, default=0.0,
                    help="L2 weight decay on head params to fight overfitting")
    ap.add_argument("--grad-clip", type=float, default=None,
                    help="max gradient norm to clip (None = no clipping)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--metrics-out", default=None,
                    help="optional JSON path to dump the CV summary + chosen config")
    ap.add_argument("--tune", action="store_true",
                    help="run a fast single-split hyperparameter sweep first, "
                         "then use the best config for the full CV + export")
    ap.add_argument("--epochs-grid", default="2,3,4",
                    help="comma-separated epochs to try during --tune")
    ap.add_argument("--lr-grid", default="1e-5,2e-5,5e-5",
                    help="comma-separated learning rates to try during --tune")
    ap.add_argument("--ratio-grid", default="4,8,16",
                    help="comma-separated max_neg_ratio values to try during --tune")
    args = ap.parse_args()

    input_dir = _resolve_input_dir(args.input_dir)
    annot = os.path.join(input_dir, "prerequisite_annotation.csv")
    topics = os.path.join(input_dir, "208topics.csv")
    name_of, pairs = load_data(annot, topics)
    X = [(a, b) for a, b, _ in pairs]
    y = [l for _, _, l in pairs]
    print(f"Loaded {len(pairs)} pairs across {len(name_of)} topics; "
          f"balance {Counter(y)}", flush=True)

    base_model = args.base_model
    if base_model is None:
        from backend.pipeline.fine_tune import _DEF_BASE
        base_model = _DEF_BASE
    print(f"Backbone: {base_model}", flush=True)

    epochs, lr, max_neg_ratio = args.epochs, args.lr, args.max_neg_ratio
    if args.tune:
        eg = [int(s) for s in args.epochs_grid.split(",")]
        lg = [float(s) for s in args.lr_grid.split(",")]
        rg = [int(s) for s in args.ratio_grid.split(",")]
        print("\nTuning hyperparameters on a single split...", flush=True)
        epochs, lr, max_neg_ratio = tune_hyperparams(
            X, y, epochs_grid=eg, lr_grid=lg, ratio_grid=rg,
            batch_size=args.batch_size, base_model=base_model,
            weight_decay=args.weight_decay, grad_clip=args.grad_clip,
            device=args.device,
        )

    result = run_cv(
        X, y,
        max_neg_ratio=max_neg_ratio,
        epochs=epochs,
        batch_size=args.batch_size,
        lr=lr,
        base_model=base_model,
        weight_decay=args.weight_decay,
        grad_clip=args.grad_clip,
        device=args.device,
    )

    # Final model on ALL data for deployment.
    print("\nFine-tuning final model on all data...", flush=True)
    triples = build_train_triples(X, y, max_neg_ratio=max_neg_ratio)
    model, tok = fine_tune_cross_encoder(
        triples, epochs=epochs, batch_size=args.batch_size,
        lr=lr, base_model=base_model,
        weight_decay=args.weight_decay, grad_clip=args.grad_clip,
        device=args.device,
    )
    out = export_model(model, tok, args.output_dir)
    print(f"Exported fine-tuned model to {out}", flush=True)

    if args.metrics_out:
        with open(args.metrics_out, "w", encoding="utf-8") as f:
            json.dump({
                "config": {
                    "epochs": epochs, "lr": lr,
                    "max_neg_ratio": max_neg_ratio, "batch_size": args.batch_size,
                    "base_model": base_model, "weight_decay": args.weight_decay,
                    "grad_clip": args.grad_clip, "used_tune": args.tune,
                },
                "cv": result,
                "tuned_f1": round(result["avgs"]["f1"], 4),
            }, f, indent=2)
        print(f"Wrote metrics to {args.metrics_out}", flush=True)



if __name__ == "__main__":
    main()
