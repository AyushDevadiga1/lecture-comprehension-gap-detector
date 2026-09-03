"""Live-UI smoke test: drive the exact HTTP calls the Streamlit frontend makes,
against the app backed by the seeded smoke DB (data/smoke_lecgap.db), via an
in-process FastAPI TestClient (same routing/DB/worker stack uvicorn serves).

Verifies the wiring a real `streamlit run` session depends on, including the
st.video(remediation clip) path resolving to a real, movable file.
"""

import os
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

print("\n== 2. course graph fetch ==")
r = client.get("/courses/ml/graph")
check("GET /courses/ml/graph 200", r.status_code == 200)
graph = r.json()
print("   learner order:", graph.get("topological_order"))

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
for q in qs:
    correct = q["concept"] not in fail_these
    answers.append({
        "question_id": q["id"],
        "selected": "correct" if correct else "incorrect",
        "correct": correct,
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
