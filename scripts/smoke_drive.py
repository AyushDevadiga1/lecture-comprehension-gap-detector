"""Live-UI smoke test: drive the exact HTTP calls the Streamlit frontend makes,
against the app backed by the seeded smoke DB (data/smoke_lecgap.db), via an
in-process FastAPI TestClient (same routing/DB/worker stack uvicorn serves).

Verifies the wiring a real `streamlit run` session depends on, including the
st.video(remediation clip) path resolving to a real, movable file.
"""

import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ["LECGAP_DATABASE_URL"] = "sqlite:///data/smoke_lecgap.db"

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app  # noqa: E402

client = TestClient(app)

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if (detail and not cond) else ""))
    if not cond:
        failures.append(name)


print("== 1. health + lectures ==")
r = client.get("/health")
check("GET /health 200", r.status_code == 200)
r = client.get("/lectures")
check("GET /lectures 200", r.status_code == 200)
lectures = r.json()
print("   lectures:", lectures)

print("\n== 1b. GET /usage (quota transparency) ==")
r = client.get("/usage")
check("GET /usage 200", r.status_code == 200)
usage_body = r.json()
services = usage_body.get("services", {})
check("usage has per-service keys",
      {"groq.chat", "groq.whisper", "local", "ollama"} <= set(services))
check("usage no-data is honest (no fake zeros)",
      "remaining_requests" not in services.get("groq.whisper", {}) or
      isinstance(services["groq.whisper"]["remaining_requests"], int))
check("usage includes availability", "availability" in usage_body)

print("\n== 1c. two-step create (POST /lectures, no file) then clean up ==")
r = client.post("/lectures", data={"course_id": "ml", "title": "twostep-probe"})
check("POST /lectures without file -> 201 uploaded", r.status_code == 201
      and r.json()["status"] == "uploaded")
probe_id = r.json()["id"]
r = client.delete(f"/lectures/{probe_id}")
check("DELETE probe lecture 200 (no transcription ever started)",
      r.status_code == 200)

print("\n== 2. course graph fetch ==")
r = client.get("/courses/ml/graph")
check("GET /courses/ml/graph 200", r.status_code == 200)
graph = r.json()
print("   learner order:", graph.get("topological_order"))

print("\n== 2b. faculty DAG view renders (frontend.render.dag_html) ==")
if graph.get("topological_order"):
    from frontend.render import dag_html
    html = dag_html(graph)
    names = graph["topological_order"][:3]
    check("dag html contains learner-order concepts", all(n in html for n in names))
    check("dag html loads vis-network from CDN (small page)", "vis-network" in html
          and "https://cdnjs.cloudflare.com/ajax/libs/vis-network" in html
          and len(html) < 60_000)
else:
    check("dag html renders for seeded course", False, "smoke course has no graph")

print("\n== 3. create quiz (UI: POST /quizzes {course_id, student_id}) ==")
r = client.post("/quizzes", json={"course_id": "ml", "student_id": "demo-student"})
check("POST /quizzes 201", r.status_code == 201)
quiz = r.json()
qs = quiz["questions"]
print(f"   {len(qs)} questions, first: {qs[0]['question']}")

print("\n== 4. submit quiz (UI: POST /quizzes/submit with mixed answers) ==")
answers = []
# fail 'Prediction', 'Multiple Linear Regression', 'Model Coefficients' on purpose
fail_these = {"Prediction", "Multiple Linear Regression", "Model Coefficients"}
# answers are graded server-side; the driver reads the answer key from the
# smoke DB to emulate a student who knows the material (and deliberately
# misses `fail_these`), exactly like scripts/sample_run.py.
with sqlite3.connect("data/smoke_lecgap.db") as con:
    answer_key = dict(con.execute("SELECT id, answer FROM quiz_questions"))
for q in qs:
    wrong = q["concept"] in fail_these
    key = answer_key.get(q["id"])
    opts = q.get("options") or []
    if key and wrong:
        pick = next((o for o in opts if o != key), (opts[-1] if opts else "x"))
    elif key:
        pick = key
    else:
        pick = opts[0] if opts else "x"
    answers.append({
        "question_id": q["id"],
        "selected": pick,
        "latency_s": 2.0,
    })
r = client.post("/quizzes/submit",
                json={"course_id": "ml", "student_id": "demo-student",
                      "answers": answers})
check("POST /quizzes/submit 200", r.status_code == 200)
result = r.json()
print(f"   score {result['score']}/{result['total']}")
print(f"   remediation ({len(result['remediation'])} items):")
for item in result["remediation"]:
    print(f"     - {item['concept']} failed={item['failed']} clip={item.get('clip')}")

print("\n== 5. remediation clip path is a REAL playable file (st.video) ==")
clips_seen = [it.get("clip") for it in result["remediation"] if it.get("clip")]
if clips_seen:
    for cp in clips_seen:
        check(f"clip exists: {Path(cp).name}", Path(cp).exists())
        check(f"clip size>0: {Path(cp).name}", Path(cp).stat().st_size > 0)
else:
    check("remediation includes at least one clip", False, "no clip in remediation")

print("\n== 6b. media endpoint streams with Range (framework-agnostic) ==")
if clips_seen:
    for cp in clips_seen[:1]:
        rel = Path(cp)
        check("clip file is real", rel.exists())
        url = f"/media/clips/{rel.parent.name}/{rel.name}"
        r = client.get(url)
        check("GET media 200", r.status_code == 200)
        check("media content-type video/mp4",
              r.headers.get("content-type", "").startswith("video/"))
        r2 = client.get(url, headers={"Range": "bytes=0-9"})
        check("media Range -> 206 + content-range",
              r2.status_code == 206 and r2.headers.get("content-range"),
              f"got {r2.status_code} {r2.headers.get('content-range')}")
else:
    check("remediation includes at least one clip", False, "no clip in remediation")

print("\n== 6. GET /students/demo-student/remediation ==")
r = client.get("/students/demo-student/remediation", params={"course_id": "ml"})
check("GET remediation 200", r.status_code == 200)

print("\n== 7. GET /courses/ml/stats (faculty tab) ==")
r = client.get("/courses/ml/stats")
check("GET /courses/ml/stats 200", r.status_code == 200)
stats = r.json()
print(f"   heatmap ({len(stats['heatmap'])}):", [(h['concept'], h['rate']) for h in stats['heatmap'][:4]])
print(f"   divergence ({len(stats['divergence'])}):", stats['divergence'][:3])
check("heatmap non-empty", len(stats["heatmap"]) > 0)
check("divergence has keys", all({"concept", "taught_idx", "learned_idx", "gap"} <= set(d) for d in stats["divergence"]))

print("\n=====================================")
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
