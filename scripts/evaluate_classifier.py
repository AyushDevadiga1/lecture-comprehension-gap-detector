"""
Phase 3 evaluation — benchmark the prerequisite classifier against LectureBank 1.0.

Reads data/lecturebank/ (prerequisite_annotation.csv + 208topics.csv), builds
all labeled (A, B) pairs, then cross-validates the PrerequisiteClassifier and
reports precision / recall / F1 per EVALUATION.md (Claim 1).

Reads data/lecturebank/ (git-ignored; download populates it):
  prerequisites_annotation.csv::(Source_Topic_ID, Target_Topic_ID, If_prerequisite)
  208topics.csv::(id, Topic, Topic_Link)

Usage:
  & D:\\Anaconda3\\envs\\lecgap\\python.exe scripts/evaluate_classifier.py
"""

import csv
import os
from collections import Counter

from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import StratifiedKFold

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.pipeline.classify_prerequisites import PrerequisiteClassifier

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "lecturebank")
ANNOT_FILE = os.path.join(DATA_DIR, "prerequisite_annotation.csv")
TOPICS_FILE = os.path.join(DATA_DIR, "208topics.csv")


def load_data():
    """Return (topic_id -> name) map and ordered list of (name_a, name_b, label)."""
    name_of = {}
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                name_of[row[0]] = row[1]

    pairs = []
    with open(ANNOT_FILE, newline="", encoding="utf-8") as f:
        for src, tgt, label in csv.reader(f):
            if src in name_of and tgt in name_of:
                pairs.append((name_of[src], name_of[tgt], int(label)))
    return name_of, pairs


def run_cv(X, y, *, fit_kwargs=None, label=""):
    fit_kwargs = fit_kwargs or {}
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    folds_p, folds_r, folds_f1, folds_acc, fold_thr = [], [], [], [], []

    for fold, (tr_idx, te_idx) in enumerate(skf.split(X, y)):
        # carve a validation slice out of the training fold to pick the
        # decision threshold — the TEST set is never used for tuning.
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

        clf = PrerequisiteClassifier().fit(tr_pairs, tr_labels, **fit_kwargs)
        va_probs = clf.predict_proba(va_pairs)

        # pick the best threshold on the validation slice only
        best = (0.0, 0.5)
        for t in [i / 100 for i in range(20, 76)]:
            preds = [1 if p >= t else 0 for p in va_probs]
            f = f1_score(va_labels, preds, zero_division=0)
            if f > best[0]:
                best = (f, t)
        fold_thr.append(best[1])

        probs = clf.predict_proba(te_pairs)
        preds = [1 if p >= best[1] else 0 for p in probs]

        folds_p.append(precision_score(te_labels, preds, zero_division=0))
        folds_r.append(recall_score(te_labels, preds, zero_division=0))
        folds_f1.append(f1_score(te_labels, preds, zero_division=0))
        folds_acc.append(sum(p == t for p, t in zip(preds, te_labels)) / len(te_labels))
        print(
            f"  fold {fold + 1}: P={folds_p[-1]:.3f} R={folds_r[-1]:.3f} "
            f"F1={folds_f1[-1]:.3f} @thr={best[1]:.2f}"
        )

    n = len(folds_p)
    print(f"\n=== 5-fold CV summary [{label}] ===")
    print(f"Precision (avg): {sum(folds_p) / n:.3f}")
    print(f"Recall    (avg): {sum(folds_r) / n:.3f}")
    print(f"F1        (avg): {sum(folds_f1) / n:.3f}")
    print(f"Accuracy  (avg): {sum(folds_acc) / n:.3f}")
    print(f"Threshold (avg): {sum(fold_thr) / n:.2f}")


def main():
    name_of, pairs = load_data()
    X = [(a, b) for a, b, _ in pairs]
    y = [lbl for _, _, lbl in pairs]

    print(f"Loaded {len(pairs)} labeled pairs across {len(name_of)} topics")
    print("Class balance:", Counter(y))

    run_cv(X, y, fit_kwargs={"balance": "undersample", "max_neg_ratio": 16}, label="concat+interactions, us 1:16, thr from val slice")


if __name__ == "__main__":
    main()
