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
            "**Output:** the fine-tuned model is written to `/kaggle/working/model/` — download\n"
            "it (the `model/` folder) and load it on CPU for inference in the LecGap pipeline.\n"
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
        _code(
            "INPUT_DIR = '/kaggle/input/datasets/ayushdevadiga/lecturebank'\n"
            "\n"
            "# --tune runs a fast single-split sweep over the grids below, picks the\n"
            "# best (epochs, lr, max_neg_ratio) by val-F1, then runs the full 5-fold\n"
            "# CV and exports the final model with that config. Edit the grids to\n"
            "# shrink/expand the search (each config trains once on a single split).\n"
            "!python /kaggle/working/kaggle_fine_tune.py \\\n"
            "    --input-dir {INPUT_DIR} \\\n"
            "    --output-dir /kaggle/working/model \\\n"
            "    --batch-size 32 \\\n"
            "    --tune \\\n"
            "    --epochs-grid 2,3 \\\n"
            "    --lr-grid 1e-5,2e-5,5e-5 \\\n"
            "    --ratio-grid 4,8\n"
            "\n"
            "print('\\nBest-config 5-fold CV done; fine-tuned model is in /kaggle/working/model/ — download for CPU inference.')"
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
