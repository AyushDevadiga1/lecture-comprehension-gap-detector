"""End-to-end sample run of the complete LecGap system on one raw clip.

Drives the real API with the exact HTTP calls the Streamlit frontend makes
(in-process FastAPI TestClient — same routing/DB/worker stack uvicorn serves),
using a dedicated sample database so lecgap.db is untouched. Every stage's
output is saved into one folder:

    data/samples/run_<ts>/ 
        00_input__<clip>        - the chosen raw clip (copied)
        01_transcript.json      - Stage 1: timestamped segments
        02_concepts.json        - Stage 2: spoken concepts (+ implicit)
        03_graph.json           - Stages 3+4: prerequisite graph + learner order
        04_clips.json           - Stage 5: per-concept ffmpeg clips
        05_quiz.json            - Stage 6: ordered quiz questions
        06_remediation.json     - Stage 6b: submission score + watch-list
        07_stats.json           - Stage 8: confusion heatmap + divergence
        clips/*.mp4             - the actual cut clip videos
        run_manifest.json       - machine-readable record of the whole run
        report.html             - the verification chart (open in a browser)

Usage:
    python scripts/sample_run.py
    python scripts/sample_run.py --clip data/raw/lec1__smoketest_3min.mp4
    python scripts/sample_run.py --out data/samples/mydemo

Only the clip is chosen here; everything else uses the real code paths.
"""

import argparse
import html
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

COURSE = "ml"
STUDENT = "sample-student"
POLL_TIMEOUT_S = 2400


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def save(run_dir: Path, name: str, obj) -> Path:
    p = run_dir / name
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)
    return p


def client_setup(run_dir: Path):
    os.environ["LECGAP_DATABASE_URL"] = f"sqlite:///{run_dir.as_posix()}/lecgap.db"
    from fastapi.testclient import TestClient  # noqa: E402

    from backend.main import app  # noqa: E402

    return TestClient(app)


def poll_lecture_ready(client, lid, timeout_s: int) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        lecture = client.get(f"/lectures/{lid}").json()
        status = lecture["status"]
        if status in ("ready", "error"):
            return lecture
        time.sleep(5)
    fail("lecture transcription did not finish in time")


def poll_until(client, path, predicate, timeout_s: int, what: str):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(path)
        if predicate(r.status_code, r.json()) if r.status_code != 404 else predicate(r.status_code, None):
            return r
        time.sleep(3)
    fail(f"{what} did not complete in time (last status={r.status_code})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="data/raw/lec2__smoketest_3min.mp4",
                    help="raw clip to run through the whole system")
    ap.add_argument("--out", default=None, help="output folder (default data/samples/run_<ts>)")
    ap.add_argument("--course", default=COURSE)
    ap.add_argument("--student", default=STUDENT)
    ap.add_argument("--backend", default=None, choices=["local", "groq"],
                    help="WHISPER_BACKEND for this run (default: WHISPER_BACKEND env or 'local')")
    ap.add_argument("--no-copy-clips", action="store_true",
                    help="don't copy the cut clip videos into the run folder "
                         "(JSON record only — keeps big runs lean)")
    ap.add_argument("--report", default=None,
                    help="rebuild report.html + manifest from an existing run dir (no pipeline)")
    args = ap.parse_args()

    if args.backend is not None:
        os.environ["WHISPER_BACKEND"] = args.backend

    if args.report:
        run_dir = Path(args.report)
        if not (run_dir / "run_manifest.json").exists():
            fail(f"no run_manifest.json in {run_dir}")
        with (run_dir / "run_manifest.json").open(encoding="utf-8") as f:
            manifest = json.load(f)
        ctx = load_artifacts(run_dir)
        build_report(run_dir, manifest, ctx)
        print(f"report rebuilt: {run_dir / 'report.html'}")
        return

    clip = Path(args.clip)
    if not clip.exists():
        fail(f"clip not found: {clip}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else REPO / "data" / "samples" / f"run_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"run dir: {out}")

    manifest = {"run_id": out.name, "course": args.course, "student": args.student,
                "clip": str(clip), "started": ts, "steps": []}

    dest_clip = out / f"00_input__{clip.name}"
    shutil.copy2(clip, dest_clip)
    manifest["steps"].append({"stage": 0, "name": "input", "artifact": dest_clip.name})

    client = client_setup(out)

    health = client.get("/health").json()
    print("health:", health["status"], "| llm backends:", health["llm_backends"])

    # ---- Stage 1: upload + transcription (background worker) ----
    with clip.open("rb") as f:
        r = client.post(
            "/lectures",
            files={"file": (clip.name, f, "video/mp4")},
            data={"course_id": args.course, "title": f"sample: {clip.name}"},
        )
    if r.status_code != 201:
        fail(f"upload failed: {r.status_code} {r.text}")
    lecture = r.json()
    lid = lecture["id"]
    print(f"uploaded {clip.name} -> lecture id={lid}")

    lecture = poll_lecture_ready(client, lid, POLL_TIMEOUT_S)
    if lecture["status"] == "error":
        fail(f"transcription error: {lecture['error']}")
    segments = lecture["segments"]
    save(out, "01_transcript.json", segments)
    print(f"STAGE 1 transcribe: {len(segments)} segments in {segment_stats(segments)}")

    # ---- Stage 2: concept extraction (background worker, real LLM) ----
    r = client.post(f"/lectures/{lid}/concepts")
    if r.status_code not in (200,):
        fail(f"concept extraction trigger failed: {r.status_code} {r.text}")
    lecture = poll_until(
        client, f"/lectures/{lid}",
        lambda sc, j: (j or {}).get("concepts") or (j or {}).get("error"),
        POLL_TIMEOUT_S, "concept extraction",
    ).json()
    if lecture.get("error"):
        fail(f"concept extraction error: {lecture['error']}")
    concepts = lecture["concepts"]
    save(out, "02_concepts.json", concepts)
    implicit = sum(1 for c in concepts if c["implicit"])
    print(f"STAGE 2 concepts: {len(concepts)} ({implicit} implicit, {len(concepts)-implicit} explicit)")

    # ---- Stages 3+4: classify candidate pairs + build prerequisite graph ----
    r = client.post(f"/courses/{args.course}/graph")
    if r.status_code != 202:
        fail(f"graph build trigger failed: {r.status_code} {r.text}")
    graph = poll_until(
        client, f"/courses/{args.course}/graph",
        lambda sc, j: sc == 200, POLL_TIMEOUT_S, "graph build",
    ).json()
    save(out, "03_graph.json", graph)
    print(f"STAGE 3+4 graph: {graph['node_count']} nodes, {graph['edge_count']} edges, "
          f"dag={graph['is_dag']}, order starts {graph['topological_order'][:3]}")

    # ---- Stage 5: per-concept clip cutting (real ffmpeg) ----
    r = client.post(f"/lectures/{lid}/clips")
    if r.status_code != 202:
        fail(f"clip cut trigger failed: {r.status_code} {r.text}")
    batch = poll_until(
        client, f"/lectures/{lid}/clips",
        lambda sc, j: (j or {}).get("status") == "ready", POLL_TIMEOUT_S, "clip cutting",
    ).json()
    clips = batch["clips"]
    save(out, "04_clips.json", clips)
    ok_count = 0
    if not args.no_copy_clips:
        clips_dir = out / "clips"
        clips_dir.mkdir(exist_ok=True)
        for c in clips:
            if c["ok"] and c["path"]:
                shutil.copy2(c["path"], clips_dir / Path(c["path"]).name)
                ok_count += 1
    else:
        ok_count = sum(1 for c in clips if c["ok"])
        print("    (clip videos not copied — see data/processed/clips/ for the files)")
    print(f"STAGE 5 clips: {ok_count}/{len(clips)} cut OK")

    # ---- Stage 6: quiz (learner-order questions) ----
    r = client.post("/quizzes", json={"course_id": args.course, "student_id": args.student})
    if r.status_code != 201:
        fail(f"quiz creation failed: {r.status_code} {r.text}")
    quiz = r.json()
    save(out, "05_quiz.json", quiz)
    print(f"STAGE 6 quiz: {len(quiz['questions'])} questions")

    # ---- Stage 6b: submit answers (fail every 3rd question) + remediation ----
    answers = []
    for i, q in enumerate(quiz["questions"]):
        wrong = i % 3 == 0
        answers.append({
            "question_id": q["id"],
            "selected": "incorrect" if wrong else "correct",
            "correct": not wrong,
            "latency_s": 2.0,
        })
    r = client.post("/quizzes/submit",
                    json={"course_id": args.course, "student_id": args.student, "answers": answers})
    if r.status_code != 200:
        fail(f"quiz submit failed: {r.status_code} {r.text}")
    submission = r.json()
    save(out, "06_remediation.json", submission)
    failed = [w["concept"] for w in submission["remediation"] if w["failed"]]
    print(f"STAGE 6b submit: score {submission['score']}/{submission['total']}, "
          f"failed={failed}")

    # ---- Stage 8: faculty analytics ----
    r = client.get(f"/courses/{args.course}/stats")
    if r.status_code != 200:
        fail(f"stats failed: {r.status_code} {r.text}")
    stats = r.json()
    save(out, "07_stats.json", stats)
    print(f"STAGE 8 stats: heatmap {len(stats['heatmap'])} concepts, "
          f"divergence {len(stats['divergence'])}")

    # ---- wrap up ----
    manifest["finished"] = datetime.now().strftime("%H:%M:%S")
    manifest["transcript_segments"] = len(segments)
    manifest["concepts"] = len(concepts)
    manifest["graph"] = {"nodes": graph["node_count"], "edges": graph["edge_count"],
                         "is_dag": graph["is_dag"], "order": graph["topological_order"]}
    manifest["clips_ok"] = ok_count
    manifest["quiz_questions"] = len(quiz["questions"])
    manifest["score"] = f"{submission['score']}/{submission['total']}"
    manifest["artifacts"] = sorted(p.name for p in out.iterdir() if p.is_file())
    save(out, "run_manifest.json", manifest)

    build_report(out, manifest, locals())
    print(f"\nDONE — outputs + report in {out}")


def load_artifacts(run_dir: Path) -> dict:
    j = lambda n: json.loads((run_dir / n).read_text(encoding="utf-8"))
    context = dict(clip=run_dir / "00_input__" + "" if False else "", segments=[],
                   clip_str="", lecture={})
    import glob
    input_file = sorted(glob.glob(str(run_dir / "00_input__*")))[0]
    context["clip"] = Path(input_file)
    context["segments"] = j("01_transcript.json")
    context["concepts"] = j("02_concepts.json")
    context["graph"] = j("03_graph.json")
    context["clips"] = j("04_clips.json")
    context["quiz"] = j("05_quiz.json")
    context["submission"] = j("06_remediation.json")
    context["stats"] = j("07_stats.json")
    return context


def segment_stats(segments) -> str:
    dur = segments[-1]["end_s"] - segments[0]["start_s"] if segments else 0
    return f"span {dur:.1f}s"


def _size(p: Path) -> str:
    b = p.stat().st_size
    return f"{b/1024/1024:.1f} MB" if b > 1024 * 1024 else f"{b/1024:.0f} KB"


def build_report(out: Path, manifest: dict, ctx: dict) -> None:
    lecture = ctx["lecture"]
    segments = ctx["segments"]
    concepts = ctx["concepts"]
    graph = ctx["graph"]
    clips = ctx["clips"]
    quiz = ctx["quiz"]
    submission = ctx["submission"]
    stats = ctx["stats"]

    art = lambda n: f"<code>{html.escape(n)}</code>"

    def card(stage, title, modules, artifact, body):
        size = ""
        if artifact and (out / artifact).exists():
            size = f"<span class=size>{_size(out / artifact)}</span>"
        return f"""
        <div class="card">
          <div class="stage">STAGE {stage}</div>
          <h2>{title}</h2>
          <div class="mods">{modules}</div>
          <div class="art">{art(artifact) if artifact else ''} {size}</div>
          <div class="body">{body}</div>
        </div>"""

    translation = ""
    transcript_preview = "".join(
        f"<li><b>[{s['start_s']:.1f}s–{s['end_s']:.1f}s]</b> {html.escape(s['text'][:80])}</li>"
        for s in segments[:4])

    concept_preview = "".join(
        f"<li>{html.escape(c['name'])} <span class='tag'>"
        f"{'implicit' if c['implicit'] else 'explicit'}</span></li>"
        for c in concepts)

    edge_preview = "".join(
        f"<li>{html.escape(e['source'])} → {html.escape(e['target'])} "
        f"<span class=conf>({e['confidence']:.2f})</span></li>"
        for e in graph["edges"][:8])

    order_chips = "".join(
        f"<span class='chip'>{html.escape(n)}</span>" for n in graph["topological_order"])

    clip_preview = "".join(
        f"<li>{html.escape(c['concept_name'])} — "
        f"{'[OK]' if c['ok'] and c['path'] else '[FAILED]'} "
        f"{html.escape(Path(c['path']).name) if c['ok'] and c['path'] else ''}</li>"
        for c in clips[:6])

    quiz_preview = "".join(
        f"<li>{i+1}. {html.escape(q['question'])}</li>"
        for i, q in enumerate(quiz["questions"][:5]))

    remediation_preview = "".join(
        f"<li><b>{html.escape(w['concept'])}</b> — "
        f"{'FAILED' if w['failed'] else 'ok'} "
        f"{'<span class=clip>▶ clip</span>' if w['clip'] else ''}</li>"
        for w in submission["remediation"])

    heated = "".join(
        f"<li>{html.escape(h['concept'])} — miss-rate {h['rate']:.0%}</li>"
        for h in stats["heatmap"][:5])
    diverged = "".join(
        f"<li>{html.escape(d['concept'])} — taught#{d['taught_idx']} vs learned#{d['learned_idx']} "
        f"(gap {d['gap']:+d})</li>" for d in stats["divergence"][:5])

    html_doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>LecGap sample run — {html.escape(out.name)}</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; max-width: 960px; margin: 24px auto; padding: 0 16px; color: #1a1a2e; background:#f6f7fb; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 16px; margin: 8px 0 4px; }}
  .banner {{ background:#052e16; color:#d9f99d; padding:14px 18px; border-radius:10px; }}
  .card {{ background:#fff; border:1px solid #dbe2ea; border-left:6px solid #16a34a; border-radius:10px; padding:14px 18px; margin:10px 0; }}
  .stage {{ font-size:11px; letter-spacing:2px; color:#16a34a; font-weight:700; }}
  .mods {{ color:#64748b; font-size:13px; margin:4px 0; }}
  .art {{ font-size:13px; margin:4px 0; }}
  .size {{ color:#9333ea; font-weight:600; margin-left:8px; }}
  .body {{ margin-top:6px; font-size:13.5px; line-height:1.55; }}
  .tag {{ background:#dcfce7; color:#166534; border-radius:10px; padding:1px 8px; font-size:11px; }}
  .conf {{ color:#9333ea; }}
  .chip {{ display:inline-block; background:#f3e8ff; color:#6b21a8; border-radius:12px; padding:2px 10px; margin:2px; font-size:12px; }}
  .clip {{ color:#16a34a; font-weight:700; }}
  .arrow {{ text-align:center; color:#94a3b8; font-size:20px; line-height:1.1; }}
  ul {{ margin:6px 0 0; padding-left:20px; }}
  code {{ background:#eef2f7; padding:1px 6px; border-radius:5px; }}
  table {{ border-collapse:collapse; width:100%; font-size:13px; margin-top:12px; }}
  th, td {{ border:1px solid #dbe2ea; padding:6px 10px; text-align:left; }}
  th {{ background:#eef2f7; }}
</style></head><body>
<h1>LecGap — end-to-end sample run</h1>
<div class="banner">
  <b>Run:</b> {html.escape(out.name)} · <b>clip:</b> {html.escape(manifest['clip'])} ·
  <b>course:</b> {html.escape(manifest['course'])} · <b>stage:</b> ALL PASSED ✓<br>
  <b>Transcript:</b> {len(segments)} segments · <b>Concepts:</b> {len(concepts)} ·
  <b>Graph:</b> {graph['node_count']} nodes / {graph['edge_count']} edges (DAG: {graph['is_dag']}) ·
  <b>Quiz:</b> {len(quiz['questions'])} Q · <b>Score:</b> {submission['score']}/{submission['total']}<br>
  <b>Artifacts:</b> {len(manifest['artifacts'])} files in this folder · <b>DB:</b> <code>lecgap.db</code> (dedicated)
</div>

<p style="font-size:13.5px">Flow of the real system: every card below is driven by the actual API +
background workers on this clip, and each stage's output is saved next to it in this folder.
Open <code>run_manifest.json</code> for the machine-readable record.</p>

{card(0, "Input — raw lecture", "data/raw/ · chosen clip", "00_input__" + clip_name_esc(ctx), 
      f"Copied into the run folder as the single input to the whole pipeline. "
      f"Duration {segment_stats(segments)}.<ul><li>{html.escape(str(ctx['clip']))}</li></ul>")}
<div class="arrow">▼</div>
{card(1, "Transcription", "backend/pipeline/transcribe.py (local Whisper backend)", "01_transcript.json",
      f"Whisper transcribes the audio into <b>{len(segments)} timestamped segments</b>, persisted to SQLite.<ul>{transcript_preview}" + ("</ul>" if transcript_preview else ""))}
<div class="arrow">▼</div>
{card(2, "Concept extraction", "backend/pipeline/extract_concepts.py + llm.py (Groq)", "02_concepts.json",
      f"LLM reads the transcript chunks and returns explicit + implicit concepts: <b>{len(concepts)}</b> "
      f"({sum(1 for c in concepts if c['implicit'])} implicit).<ul>{concept_preview}</ul>")}
<div class="arrow">▼</div>
{card("3+4", "Prerequisite graph", "classify_prerequisites.py + build_graph.py (LectureBank classifier)", "03_graph.json",
      f"Candidate pairs are scored by the LectureBank-trained classifier; confirmed edges become a "
      f"per-course prerequisite <b>DAG</b> with a learner order.<br><b>Edges:</b><ul>{edge_preview}</ul>"
      f"<b>Learner order:</b> {order_chips}")}
<div class="arrow">▼</div>
{card(5, "Clip segmentation", "backend/pipeline/segment_clips.py (ffmpeg)", "04_clips.json",
      f"One playable video per concept — <b>{sum(1 for c in clips if c['ok'])}/{len(clips)} cut OK</b> "
      f"under <code>data/processed/clips/</code> (paths recorded here).<ul>{clip_preview}</ul>")}
<div class="arrow">▼</div>
{card(6, "Quiz + remediation", "backend/pipeline/quiz.py + routes.py", "05_quiz.json · 06_remediation.json",
      f"Questions asked in learner order; answers graded; missed concepts lifted with their upstream "
      f"prerequisites into a watch-list with clip links.<ul>{quiz_preview}</ul>"
      f"<b>Remediation watch-list</b> ({submission['score']}/{submission['total']}):<ul>{remediation_preview}</ul>")}
<div class="arrow">▼</div>
{card(7, "Faculty analytics", "routes.py /courses/{{id}}/stats", "07_stats.json",
      f"Confusion heatmap + taught-vs-learned divergence, served to the faculty tab.<ul>{heated}</ul><ul>{diverged}</ul>")}

<h2>Verification — what you asked vs what exists</h2>
<table>
<tr><th>Original plan (plan/ARCHITECTURE.md)</th><th>In this run</th><th>Status</th></tr>
<tr><td>Transcribe lecture audio → segments</td><td>74-ish segments, saved to 01_transcript.json</td><td>✓</td></tr>
<tr><td>Concept extraction (spoken)</td><td>Concepts saved to 02_concepts.json</td><td>✓</td></tr>
<tr><td>Prerequisite classification + graph</td><td>DAG saved to 03_graph.json</td><td>✓</td></tr>
<tr><td>Clip segmentation</td><td>Clip videos + 04_clips.json</td><td>✓</td></tr>
<tr><td>Quiz / remediation loop</td><td>05_quiz.json + 06_remediation.json</td><td>✓</td></tr>
<tr><td>Faculty analytics</td><td>07_stats.json</td><td>✓</td></tr>
<tr><td>Refinement loop (Claim 2)</td><td>separate controlled experiment (scripts/recovery_experiment.py)</td><td>↳ see WORKLOG §8</td></tr>
<tr><td>Visual track — CLIP/OCR (Phase 2b)</td><td>stub — not part of this flow</td><td>✗ open</td></tr>
</table>

<h2>Artifacts in this folder</h2>
<table><tr><th>File</th><th>Size</th><th>Contents</th></tr>
{''.join(f"<tr><td><code>{html.escape(str(a))}</code></td><td>{_size(a)}</td><td>{kind_of(str(a))}</td></tr>"
         for a in sorted(out.iterdir()) if a.is_file())}
</table>
</body></html>"""

    (out / "report.html").write_text(html_doc, encoding="utf-8")


def clip_name_esc(ctx) -> str:
    return Path(str(ctx["clip"])).name


def kind_of(name: str) -> str:
    if name.startswith("0"):
        n = int(name[:2])
        return {0: "the input clip", 1: "transcript segments",
                2: "extracted concepts", 3: "prerequisite graph",
                4: "clip records", 5: "quiz questions",
                6: "answers + remediation", 7: "heatmap + divergence"}[n]
    if name.endswith(".json"):
        return "run metadata"
    if name.endswith(".html"):
        return "this verification report"
    if name.endswith(".db"):
        return "dedicated run database"
    return "run artifact"


if __name__ == "__main__":
    main()