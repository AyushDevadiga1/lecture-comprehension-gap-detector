"""
Streamlit entrypoint — student + faculty views, talking to the FastAPI
backend over HTTP only (never importing backend/pipeline/* directly —
see plan/ARCHITECTURE.md, "Decoupled architecture").

Run locally with:
    streamlit run frontend/app.py
(with the backend already running: uvicorn backend.main:app --reload)
"""

import os

import requests
import streamlit as st

API = os.getenv("LECGAP_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="LecGap", layout="wide")

st.title("LecGap")
st.caption("Lecture Comprehension Gap Detector")


def _get(path: str, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, json=None, files=None, data=None):
    r = requests.post(f"{API}{path}", json=json, files=files, data=data, timeout=60)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        st.error(detail)
        return None
    return r.json()


tab_student, tab_faculty = st.tabs(["Student", "Faculty"])


def _pick_course(default="ml1"):
    courses = set()
    try:
        for lec in _get("/lectures"):
            courses.add(lec["course_id"])
    except Exception:
        pass
    return st.selectbox("Course", sorted(courses) or [default])


# --------------------------------------------------------------- student tab

with tab_student:
    st.subheader("Ingest a lecture")
    with st.form("upload_form"):
        course_id = st.text_input("Course ID", value="ml1")
        up = st.file_uploader("Lecture media (mp4/mp3/wav/m4a/mkv/mov/webm)")
        submit = st.form_submit_button("Upload")
    if submit and up:
        resp = _post(
            "/lectures",
            files={"file": (up.name, up.getvalue(), "application/octet-stream")},
            data={"course_id": course_id.strip()},
        )
        if resp:
            st.success(f"Uploaded lecture #{resp['id']} — transcribing in background.")

    st.divider()
    st.subheader("Process + quiz a course")

    st.markdown("**Run the pipeline for a course (extract → graph → clips):**")
    with st.form("process_form"):
        proc_course = st.text_input("Course to process", value="ml1")
        run = st.form_submit_button("Extract concepts + build graph")
    if run:
        lid = None
        try:
            for lec in _get("/lectures"):
                if lec["course_id"] == proc_course.strip() and lec["status"] == "ready":
                    lid = lec["id"]
                    break
        except Exception as exc:
            st.error(str(exc))
        if lid:
            _post(f"/lectures/{lid}/concepts")
            _post("/courses/" + proc_course.strip() + "/graph")
            st.success(f"Queued extraction + graph build for course '{proc_course.strip()}' (lecture {lid}).")
        else:
            st.warning("No ready lecture found for that course id — upload one first.")

    st.divider()
    st.subheader("Take the quiz")

    with st.form("quiz_form"):
        quiz_course = _pick_course(default="ml1")
        student_id = st.text_input("Student ID", value="demo-student")
        take = st.form_submit_button("Generate quiz")
    quiz = None
    if take and quiz_course:
        quiz = _post("/quizzes", json={"course_id": quiz_course, "student_id": student_id})

    if quiz:
        with st.form("answers_form"):
            answers = []
            for q in quiz["questions"]:
                ans = st.radio(
                    f"{q['question']}",
                    options=["correct", "incorrect"],
                    key=f"q{q['id']}",
                    horizontal=True,
                )
                answers.append(
                    {"question_id": q["id"], "selected": ans,
                     "correct": ans == "correct", "latency_s": 2.0}
                )
            done = st.form_submit_button("Submit answers")
        if done:
            result = _post(
                "/quizzes/submit",
                json={"course_id": quiz_course, "student_id": student_id,
                      "answers": answers},
            )
            if result:
                st.write(f"Score: {result['score']}/{result['total']}")
                st.markdown("### Remediation (study in this order)")
                if not result["remediation"]:
                    st.success("Nothing to remediate — all upstream concepts mastered.")
                for item in result["remediation"]:
                    why = "⚠️ failed" if item["failed"] else "prerequisite"
                    st.write(f"- **{item['concept']}** _({why})_")
                    if item.get("clip"):
                        st.video(item["clip"])

# --------------------------------------------------------------- faculty tab

with tab_faculty:
    st.subheader("Confusion heatmap + taught-vs-learned divergence")

    with st.form("stats_form"):
        stat_course = _pick_course(default="ml1")
        view = st.form_submit_button("Load course stats")
    if view and stat_course:
        try:
            stats = _get("/courses/" + stat_course.strip() + "/stats")
        except Exception as exc:
            st.error(str(exc))
            stats = None
        if stats:
            st.markdown("**Wrong-answer rates (highest first):**")
            for h in stats.get("heatmap", []):
                st.write(f"- {h['concept']}: {h['wrong']}/{h['attempts']} "
                         f"({h['rate']:.0%})")
            st.markdown("**Taught order → learned order divergence:**")
            for d in stats.get("divergence", []):
                delta = d["gap"]
                arrow = "→ later" if delta > 0 else ("← earlier" if delta < 0 else "=")
                st.write(f"- {d['concept']}: taught #{d['taught_idx']} vs "
                         f"learned #{d['learned_idx']} ({arrow})")