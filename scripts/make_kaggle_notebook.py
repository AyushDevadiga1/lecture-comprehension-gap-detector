"""Regenerates notebooks/kaggle_fine_tune.ipynb by embedding the actual
backend/pipeline/fine_tune.py and scripts/kaggle_fine_tune.py sources directly
into the notebook cells.

The notebook is fully self-contained (no GitHub fetch) so it works even when
run without network access to the repo. Re-run this any time those two source
files change so the notebook stays in sync:

  & D:\\Anaconda3\\envs\\lecgap\\python.exe scripts/make_kaggle_notebook.py
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINE_TUNE = os.path.join(ROOT, "backend", "pipeline", "fine_tune.py")
KAGGLE = os.path.join(ROOT, "scripts", "kaggle_fine_tune.py")
OUT = os.path.join(ROOT, "notebooks", "kaggle_fine_tune.ipynb")


def _md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.split("\n")}


def _code(text):
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": text.split("\n")}


def main():
    with open(FINE_TUNE, encoding="utf-8") as f:
        fine_tune_src = f.read()
    with open(KAGGLE, encoding="utf-8") as f:
        kaggle_src = f.read()

    cells = [
        _md(
            "# LecGap Phase 3 — Fine-tune prerequisite classifier (GPU)\n"
            "\n"
            "This notebook fine-tunes a cross-encoder transformer over **LectureBank 1.0**\n"
            "prerequisite pairs and evaluates it with the same nested 5-fold CV used locally.\n"
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
            "download the pretrained MiniLM checkpoint; the notebook code itself is embedded)."
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
            "Runs a hyperparameter sweep over the grids below, picks the best config by "
            "val-F1, then runs the full 5-fold CV and exports the final model. To fight "
            "the small-positive overfitting seen at 2–3 epochs, try **higher epochs** here.\n"
            "\n"
            "Outputs go to `/kaggle/working/staging/` (model + `metrics.json`). Nothing is "
            "finalized yet — the **last cell** copies the model into the shipped "
            "`/kaggle/working/model/` folder only after you verify the CV F1 beats the "
            "frozen baseline (0.569)."
        ),
        _code(
            "INPUT_DIR = '/kaggle/input/datasets/ayushdevadiga/lecturebank'\n"
            "STAGING = '/kaggle/working/staging'\n"
            "\n"
            "# Edit the grids to shrink/expand the search. Each config trains ONCE on a\n"
            "# single split, so cost = (#configs) x (avg epochs) epochs of T4 time.\n"
            "# Trying more epochs directly addresses the underfitting/overfitting we saw\n"
            "# at low epochs (2-3). Note: the missing 'classifier' head + 'position_ids'\n"
            "# notes are now suppressed (they are expected task-shape noise, not errors).\n"
            "!python /kaggle/working/kaggle_fine_tune.py \\\n"
            "    --input-dir {INPUT_DIR} \\\n"
            "    --output-dir {STAGING}/model \\\n"
            "    --metrics-out {STAGING}/metrics.json \\\n"
            "    --batch-size 32 \\\n"
            "    --tune \\\n"
            "    --epochs-grid 3,4,5 \\\n"
            "    --lr-grid 1e-5,2e-5,5e-5 \\\n"
            "    --ratio-grid 4,8\n"
            "\n"
            "print('\\nStaging done. Model in {STAGING}/model, metrics in {STAGING}/metrics.json')\n"
            "print('Now run the LAST cell to ship the model only if jagged F1 beats the baseline.')"
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
            "cell** — the final `model/` folder simply won't be produced."
        ),
        _code(
            "import json, os, shutil, glob\n"
            "\n"
            "BASELINE_F1 = 0.569  # frozen-encoder benchmark (evaluate_classifier.py)\n"
            "STAGING = '/kaggle/working/staging'\n"
            "FINAL = '/kaggle/working/model'\n"
            "\n"
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

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(nb, f, indent=1)
    print(f"Wrote {OUT} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
