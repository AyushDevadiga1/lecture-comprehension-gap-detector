"""Refresh an existing sample run so its committed folder reflects the current
pipeline: Lecture-Structure pass (passages + teach-spans + spoken links) ->
transcript-first course graph -> re-cut clips on tight spans -> LLM-written
MCQs grounded on passage text. Everything runs through the real API against
the run's dedicated DB (same TestClient path as sample_run.py); stale files in
the run folder are replaced in place and structure/eval metrics land in
08_structure.json.

Usage:
    python scripts/refresh_run.py
    python scripts/refresh_run.py --run data/samples/run_20260914_063836
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.sample_run import (  # noqa: E402
    POLL_TIMEOUT_S,
    build_report,
    fail,
    load_artifacts,
    poll_until,
    save,
)

DEFAULT_RUN = "data/samples/run_20260914_063836"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=DEFAULT_RUN)
    ap.add_argument("--model", default=None,
                    help="Groq chat model for regeneration (default: pipeline default)")
    args = ap.parse_args()

    if args.model:
        # set BEFORE importing backend so GROQ_MODEL picks it up from the process env
        os.environ["LECGAP_GROQ_MODEL"] = args.model

    run_dir = Path(args.run)
    manifest_p = run_dir / "run_manifest.json"
    if not manifest_p.exists():
        fail(f"no run_manifest.json in {run_dir}")
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    course = manifest["course"]

    os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{run_dir.as_posix()}/lecgap.db"
    # data regeneration can be patient: let LLM generation ride out Groq's
    # per-minute reset windows instead of silently falling back to evidence
    os.environ.setdefault("LECGAP_LLM_RETRIES", "6")
    os.environ.setdefault("LECGAP_LLM_SLEEP_CAP_S", "300")
    from fastapi.testclient import TestClient  # noqa: E402

    from backend.main import app  # noqa: E402

    client = TestClient(app)

    with sqlite3.connect(str(run_dir / "lecgap.db")) as con:
        lid_row = con.execute("SELECT id FROM lectures LIMIT 1").fetchone()
    if lid_row is None:
        fail("no lecture in the run DB")
    lid = lid_row[0]
    print(f"refreshing lecture id={lid}, course={course} in {run_dir}")

    # ---- Stage 2: Lecture-Structure pass (concept extraction) ----
    # a stale error from an earlier failed run would trip the post-extraction
    # check below even after a clean re-run, so drop it first
    with sqlite3.connect(str(run_dir / "lecgap.db")) as con:
        con.execute("UPDATE lectures SET error = NULL")
        con.commit()
    client.post(f"/lectures/{lid}/concepts")
    lecture = poll_until(
        client, f"/lectures/{lid}",
        lambda sc, j: (j or {}).get("concepts") or (j or {}).get("error"),
        POLL_TIMEOUT_S, "concept extraction",
    ).json()
    if lecture.get("error"):
        fail(f"concept extraction error: {lecture['error']}")
    concepts = lecture["concepts"]
    save(run_dir, "02_concepts.json", concepts)
    print(f"STAGE 2 structure pass: {len(concepts)} concepts "
          f"(teach-spans come from the pass itself)")

    # ---- Stage 3/4: rebuild the course graph over the fresh concept set ----
    # the extraction worker already chained a rebuild; POSTing again is
    # idempotent and just re-answers the poll below. create_quiz orders
    # questions by this graph, so a fresh build matters before Stage 6.
    if client.post(f"/courses/{course}/graph").status_code != 202:
        fail("graph build trigger failed")
    graph = poll_until(
        client, f"/courses/{course}/graph",
        lambda sc, j: sc == 200, POLL_TIMEOUT_S, "graph build",
    ).json()
    save(run_dir, "03_graph.json", graph)
    src_methods: dict = {}
    for e in graph["edges"]:
        m = e.get("source_method", "classifier")
        src_methods[m] = src_methods.get(m, 0) + 1
    print(f"STAGE 3/4 course graph: {graph['node_count']} nodes, "
          f"{graph['edge_count']} edges "
          f"({', '.join(f'{m}: {n}' for m, n in src_methods.items())}), "
          f"order starts {graph['topological_order'][:3]}")

    # ---- Lecture Structure artifacts: passages + spoken links + eval stats ----
    with sqlite3.connect(str(run_dir / "lecgap.db")) as con:
        passages = [
            {"title": r[0], "kind": r[1], "start_s": r[2], "end_s": r[3],
             "summary": r[4], "text": r[5]}
            for r in con.execute(
                "SELECT title, kind, start_s, end_s, summary, text "
                "FROM passages WHERE lecture_id = ? ORDER BY idx", (lid,)
            )
        ]
        n_links = con.execute(
            "SELECT count(*) FROM lecture_links WHERE lecture_id = ?", (lid,)
        ).fetchone()[0]
    spans = [c["end_s"] - c["start_s"] for c in concepts
             if c["start_s"] is not None and c["end_s"] is not None]
    sorted_spans = sorted(spans)
    metrics = {
        "n_passages": len(passages),
        "n_spoken_links": n_links,
        "n_concepts": len(concepts),
        "n_spanned": len(sorted_spans),
        "tight_le_120s": sum(1 for s in sorted_spans if s <= 120),
        "median_span_s": sorted_spans[len(sorted_spans) // 2] if sorted_spans else None,
        "max_span_s": sorted_spans[-1] if sorted_spans else None,
        "edge_methods": src_methods,
    }
    save(run_dir, "08_structure.json", {"passages": passages, "metrics": metrics})
    print(f"STRUCTURE: {len(passages)} passages, {n_links} spoken links, "
          f"{metrics['tight_le_120s']}/{len(sorted_spans)} concepts tight <=120s, "
          f"median span {metrics['median_span_s']}s, "
          f"longest span {metrics['max_span_s']}s")

    # ---- Stage 5: re-cut clips on the refined spans ----
    client.post(f"/lectures/{lid}/clips")
    batch = poll_until(
        client, f"/lectures/{lid}/clips",
        lambda sc, j: (j or {}).get("status") == "ready", POLL_TIMEOUT_S, "clip cutting",
    ).json()
    clips = batch["clips"]
    save(run_dir, "04_clips.json", clips)
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    for f in clips_dir.glob("*.mp4"):
        f.unlink()
    ok_count = 0
    for c in clips:
        if c["ok"] and c["path"]:
            shutil.copy2(c["path"], clips_dir / Path(c["path"]).name)
            ok_count += 1
    print(f"STAGE 5 clips: {ok_count}/{len(clips)} cut OK on refined windows")

    # ---- Stage 6: LLM-written quiz (with explanation per option) ----
    quiz = client.post("/quizzes",
                       json={"course_id": course, "student_id": "sample-student"})
    if quiz.status_code != 201:
        fail(f"quiz failed: {quiz.status_code} {quiz.text}")
    quiz = quiz.json()
    save(run_dir, "05_quiz.json", quiz)
    with sqlite3.connect(str(run_dir / "lecgap.db")) as con:
        n_expl = con.execute(
            "SELECT count(*) FROM quiz_questions WHERE explanation IS NOT NULL"
        ).fetchone()[0]
    print(f"STAGE 6 quiz: {len(quiz['questions'])} questions "
          f"({n_expl} with LLM explanation + why-wrong)")

    # ---- Stage 6b: driver submit (fail every 3rd) + remediation ----
    # the run DB holds a previous submission's rows; restart the record clean
    with sqlite3.connect(str(run_dir / "lecgap.db")) as con:
        con.execute(f"DELETE FROM quiz_responses WHERE student_id = 'sample-student'")
        con.commit()
        key = dict(con.execute("SELECT id, answer FROM quiz_questions"))
    answers = []
    for i, q in enumerate(quiz["questions"]):
        wrong = i % 3 == 0
        k = key.get(q["id"])
        opts = q.get("options") or []
        if k and wrong:
            pick = next((o for o in opts if o != k), opts[-1] if opts else "x")
        elif k:
            pick = k
        else:
            pick = opts[0] if opts else "x"
        answers.append({"question_id": q["id"], "selected": pick, "latency_s": 2.0})
    sub = client.post("/quizzes/submit",
                      json={"course_id": course, "student_id": "sample-student",
                            "answers": answers})
    if sub.status_code != 200:
        fail(f"submit failed: {sub.status_code} {sub.text}")
    submission = sub.json()
    save(run_dir, "06_remediation.json", submission)
    print(f"STAGE 6b submit: score {submission['score']}/{submission['total']}")

    # ---- Stage 8: stats ----
    stats = client.get(f"/courses/{course}/stats")
    if stats.status_code != 200:
        fail(f"stats failed: {stats.status_code} {stats.text}")
    save(run_dir, "07_stats.json", stats.json())

    # ---- wrap up: manifest + report ----
    manifest["clips_ok"] = ok_count
    manifest["quiz_questions"] = len(quiz["questions"])
    manifest["score"] = f"{submission['score']}/{submission['total']}"
    manifest["artifacts"] = sorted(p.name for p in run_dir.iterdir() if p.is_file())
    save(run_dir, "run_manifest.json", manifest)

    ctx = load_artifacts(run_dir)
    build_report(run_dir, manifest, ctx)
    print(f"\nDONE — {run_dir} refreshed; report rebuilt.")


if __name__ == "__main__":
    main()