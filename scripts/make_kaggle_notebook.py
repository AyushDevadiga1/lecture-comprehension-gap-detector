"""Regenerates the Kaggle fine-tune notebooks by embedding the actual
backend/pipeline/fine_tune.py and scripts/kaggle_fine_tune.py sources directly
into notebook cells.

The notebooks are fully self-contained (no GitHub fetch) so they work even when
run without network access to the repo. Re-run this any time those source files
change so the notebooks stay in sync:

  & D:\\Anaconda3\\envs\\lecgap\\python.exe scripts/make_kaggle_notebook.py            (MiniLM)
  & D:\\Anaconda3\\envs\\lecgap\\python.exe scripts/make_kaggle_notebook.py --backbone mpnet   (bigger backbone)
"""

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINE_TUNE = os.path.join(ROOT, "backend", "pipeline", "fine_tune.py")
KAGGLE = os.path.join(ROOT, "scripts", "kaggle_fine_tune.py")

# Backbone presets: <backbone> -> notebook filename, HF model id, and a tuning
# grid sized to that model (bigger models = more time per epoch, so fewer epochs
# and a smaller learning rate).
PRESETS = {
    "minilm": {
        "out": "kaggle_fine_tune.ipynb",
        "base_model": "sentence-transformers/all-MiniLM-L6-v2",
        "title": "MiniLM cross-encoder fine-tune",
        "batch_size": 32,
        "epochs_grid": "8,10,12",
        "lr_grid": "2e-5,5e-5",
        "ratio_grid": "8",
        # MiniLM has kept improving with more epochs (e3->0.49, e5->0.53,
        # e8->0.554); push further + add weight-decay/grad-clip to cut the
        # val-vs-CV overfitting gap.
        "sweep_note": (
            "MiniLM has been improving with every epoch bump (e3->0.49, e5->0.53, "
            "e8->0.554); this sweep pushes to 8/10/12 and adds weight-decay + "
            "grad-clip to close the val-vs-CV overfitting gap."
        ),
    },
    "mpnet": {
        "out": "kaggle_fine_tune_mpnet.ipynb",
        "base_model": "sentence-transformers/all-mpnet-base-v2",
        "title": "Bigger-backbone (MPNet) cross-encoder fine-tune",
        "batch_size": 16,
        "epochs_grid": "3,4,5",
        "lr_grid": "1e-5,2e-5",
        "ratio_grid": "8",
        "sweep_note": (
            "MPNet (~420M params) has ~4-5x more capacity than MiniLM, so fewer "
            "epochs and a smaller learning rate are used. This is the 'better "
            "alternative' hypothesis: if the 913-positive pool is capacity-starved "
            "by MiniLM, a bigger backbone should finally beat the frozen baseline."
        ),
    },
}


def _md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.split("\n")}


def _code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text.split("\n")}


def build_notebook(preset):
    with open(FINE_TUNE, encoding="utf-8") as f:
        fine_tune_src = f.read()
    with open(KAGGLE, encoding="utf-8") as f:
        kaggle_src = f.read()

    p = preset
    title = p["title"]
    base_model = p["base_model"]
    batch_size = p["batch_size"]
    epochs_grid = p["epochs_grid"]
    lr_grid = p["lr_grid"]
    ratio_grid = p["ratio_grid"]
    sweep_note = p["sweep_note"]

    cells = [
        _md(
            f"# LecGap Phase 3 — {title} (GPU)\n"
            "\n"
            "Fine-tunes a cross-encoder transformer over **LectureBank 1.0** "
            f"prerequisite pairs (backbone **`{base_model}`**) and evaluates it with the "
            "same nested 5-fold CV used locally.\n"
            "\n"
            "**Input (Kaggle dataset):** two CSVs are expected at\n"
            "`/kaggle/input/datasets/ayushdevadiga/lecturebank/`\n"
            "    - `prerequisite_annotation.csv` — `(Source_Topic_ID, Target_Topic_ID, If_prerequisite)`\n"
            "    - `208topics.csv` — `(id, Topic, Topic_Link)`\n"
            "If your dataset lives at a different path, update `INPUT_DIR` in the training cell below.\n"
            "\n"
            "**Output:** training writes to `/kaggle/working/staging/` (model + `metrics.json`,\n"
            "with `UNEXPECTED`/`MISSING` load-report noise suppressed). The **last cell** — which\n"
            "you run **manually after verifying the CV F1 beats the frozen baseline (0.569)** —\n"
            "copies the model into the shipped `/kaggle/working/model/` folder. Download that\n"
            "`model/` folder and load it on CPU for inference in the LecGap pipeline.\n"
            "\n"
            "Set **Accelerator = GPU T4** and **Internet = On** (Internet is only needed to\n"
            "download the pretrained checkpoint; the notebook code itself is embedded)."
        ),
        _code(
            "import torch\n"
            "print('GPU available:', torch.cuda.is_available())\n"
            "print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"
        ),
        _code(
            "!pip install -q transformers sentence-transformers datasets scikit-learn"
        ),
        _md(
            "### 1. Core module — training/export helpers\n"
            "\n"
            "This cell writes `backend/pipeline/fine_tune.py` to disk (so the subprocess can import it) and loads it."
        ),
        _code(
            f"import os\n"
            f"os.makedirs('/kaggle/working/backend/pipeline', exist_ok=True)\n"
            f"fine_tune_src = (r'''{fine_tune_src}''')\n"
            f"with open('/kaggle/working/backend/pipeline/fine_tune.py', 'w') as _f:\n"
            f"    _f.write(fine_tune_src)\n"
            f"print('wrote backend/pipeline/fine_tune.py')\n"
        ),
        _md(
            "### 2. Training + evaluation script\n"
            "\n"
            "This cell writes `scripts/kaggle_fine_tune.py` (nested 5-fold CV plus final model export)\n"
            "to `/kaggle/working/`."
        ),
        _code(
            f"kaggle_src = r'''{kaggle_src}'''\n"
            f"with open('/kaggle/working/kaggle_fine_tune.py', 'w') as f:\n"
            f"    f.write(kaggle_src)\n"
            f"print('wrote kaggle_fine_tune.py')"
        ),
        _md(
            "### 3. Train + evaluate + export (staging)\n"
            "\n"
            + sweep_note
            + "\n"
            "\n"
            "Outputs go to `/kaggle/working/staging/` (model + `metrics.json`). Nothing is "
            "finalized yet — the **last cell** copies the model into the shipped "
            "`/kaggle/working/model/` folder only after you verify the CV F1 beats the "
            "frozen baseline (0.569)."
        ),
        _code(
            (
                "INPUT_DIR = '/kaggle/input/datasets/ayushdevadiga/lecturebank'\n"
                "STAGING = '/kaggle/working/staging'\n"
                "BASE_MODEL = '%s'\n"
                "\n"
                "# Each config trains ONCE on a single split; cost = (#configs) x (avg epochs)\n"
                "# epochs of T4 time. Backbone + grids are set from the notebook preset above.\n"
                "# weight-decay + grad-clip are in to curb the val-vs-CV overfitting gap.\n"
                "# The 'classifier' head + 'position_ids' LOAD-REPORT notes are suppressed\n"
                "# (expected task-shape noise, not errors).\n"
                "!python /kaggle/working/kaggle_fine_tune.py \\\n"
                "    --input-dir {INPUT_DIR} \\\n"
                "    --output-dir {STAGING}/model \\\n"
                "    --metrics-out {STAGING}/metrics.json \\\n"
                "    --base-model {BASE_MODEL} \\\n"
                "    --batch-size %d \\\n"
                "    --weight-decay 0.01 --grad-clip 1.0 \\\n"
                "    --tune \\\n"
                "    --epochs-grid %s \\\n"
                "    --lr-grid %s \\\n"
                "    --ratio-grid %s\n"
                "\n"
                "print('\\nStaging done. Model in {STAGING}/model, metrics in {STAGING}/metrics.json')\n"
                "print('Now run the LAST cell to ship the model only if staged F1 beats the baseline.')"
            )
            % (base_model, batch_size, epochs_grid, lr_grid, ratio_grid)
        ),
        _md(
            "### 4. FINALIZE — store the model outputs (run manually)\n"
            "\n"
            "**Run this cell only after checking the staged CV F1 (below) beats the frozen "
            "baseline 0.569.**\n"
            "\n"
            "It reads `staging/metrics.json`, prints the summary, and if `F1 > 0.569` copies "
            "the fine-tuned model into the shipped `/kaggle/working/model/` folder (what you "
            "download and drop into the repo). If the run is not better, **don't run this "
            "cell** — the final `model/` folder simply won't be produced.\n"
            "\n"
            "> Make sure you run this cell in the SAME kernel session as the training cell "
            "above (i.e. after cell 3 has finished), or `staging/metrics.json` won't exist yet."
        ),
        _code(
            "import json, os, shutil, glob\n"
            "\n"
            "BASELINE_F1 = 0.569  # frozen-encoder benchmark (evaluate_classifier.py)\n"
            "STAGING = '/kaggle/working/staging'\n"
            "FINAL = '/kaggle/working/model'\n"
            "with open(os.path.join(STAGING, 'metrics.json')) as f:\n"
            "    m = json.load(f)\n"
            "cfg = m['config']\n"
            "cv = m['cv']['avgs']\n"
            "f1 = cv['f1']\n"
            "print('Tuned config : epochs=%s, lr=%s, max_neg_ratio=%s' % (\n"
            "    cfg['epochs'], cfg['lr'], cfg['max_neg_ratio']))\n"
            "print('CV F1        : %.3f  (P %.3f, R %.3f, acc %.3f)' % (\n"
            "    f1, cv['p'], cv['r'], cv['acc']))\n"
            "print('Baseline F1  : %.3f' % BASELINE_F1)\n"
            "\n"
            "beat = f1 > BASELINE_F1\n"
            "print('F1 beats baseline? %s' % beat)\n"
            "if not beat:\n"
            "    raise SystemExit('NOT finalized: tuned F1 does not beat the frozen '\n"
            "                     'baseline (0.569). No model/ folder was produced.')\n"
            "\n"
            "if os.path.isdir(FINAL):\n"
            "    shutil.rmtree(FINAL)\n"
            "shutil.copytree(os.path.join(STAGING, 'model'), FINAL)\n"
            "with open(os.path.join(FINAL, 'metrics.json'), 'w') as f:\n"
            "    json.dump(m, f, indent=2)\n"
            "print('Model stored in ' + FINAL + ':')\n"
            "for p in sorted(glob.glob(FINAL + '/**/*', recursive=True)):\n"
            "    if os.path.isfile(p):\n"
            "        print('  ', p, os.path.getsize(p))\n"
            "print('Download /kaggle/working/model/ and drop it into the repo as '\n"
            "      'data/models/lecgap_ft/ for CPU inference.')"
        ),
    ]

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10"},
        },
        "nbformat": 4,
        "nbformat_minor": 4,
    }

    out = os.path.join(ROOT, "notebooks", p["out"])
    with open(out, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1)
    print(f"Wrote {out} ({len(cells)} cells)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backbone", choices=sorted(PRESETS), default="minilm")
    args = ap.parse_args()
    build_notebook(PRESETS[args.backbone])


if __name__ == "__main__":
    main()
