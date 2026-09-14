"""Regenerate a sample run's quiz with Stage 6c (cached LLM MCQs).

Drives the real API against a run's dedicated DB (the same TestClient path as
sample_run.py) so the committed run folder ends up with the best available
question-generation path: POST /quizzes now asks the cached LLM to write each
MCQ (real definition + plausible distractors) and falls back to evidence only
on a miss. The refreshed 05_quiz.json is written back into the run dir.

A regeneration is a one-time cost: every LLM call is cached per prompt, so
rerunning this script (or reloading the quiz in the UI) is instant.

Usage:
    python scripts/regenerate_quiz.py
    python scripts/regenerate_quiz.py --run data/samples/run_20260914_063836
    python scripts/regenerate_quiz.py --sample 8
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_RUN = "data/samples/run_20260914_063836"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=DEFAULT_RUN)
    ap.add_argument("--sample", type=int, default=8,
                    help="how many regenerated questions to print")
    args = ap.parse_args()

    run_dir = Path(args.run)
    if not (run_dir / "run_manifest.json").exists():
        sys.exit(f"no run_manifest.json in {run_dir}")
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    course = manifest["course"]

    os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{run_dir.as_posix()}/lecgap.db"
    from fastapi.testclient import TestClient  # noqa: E402

    from backend.main import app  # noqa: E402

    client = TestClient(app)

    t0 = time.time()
    r = client.post("/quizzes", json={"course_id": course, "student_id": "sample-student"})
    if r.status_code != 201:
        sys.exit(f"quiz regeneration failed: {r.status_code} {r.text}")
    quiz = r.json()
    elapsed = time.time() - t0

    (run_dir / "05_quiz.json").write_text(
        json.dumps(quiz, indent=2, default=str), encoding="utf-8"
    )

    with sqlite3.connect(str(run_dir / "lecgap.db")) as con:
        key = dict(con.execute("SELECT id, answer FROM quiz_questions"))
    rows = sorted(quiz["questions"], key=lambda q: q["id"])

    print(f"regenerated {len(rows)} questions for course {course} "
          f"in {elapsed:.0f}s -> {run_dir / '05_quiz.json'}")
    for q in rows[: args.sample]:
        ans = key.get(q["id"])
        opts = q["options"]
        print("\nQ: " + q["question"])
        for o in opts:
            tag = " [ANSWER]" if o == ans else ""
            print(f"   {o}{tag}")
    print(f"\n({len(rows)} questions -> answer key read from {run_dir}/lecgap.db, "
          f"server never leaked it through the API)")


if __name__ == "__main__":
    main()