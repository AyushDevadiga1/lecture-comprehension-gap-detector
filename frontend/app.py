"""
Streamlit entrypoint — student + faculty views, talking to the FastAPI
backend over HTTP only (never importing backend/pipeline/* directly —
see plan/ARCHITECTURE.md, "Decoupled architecture").

Run locally with:
    streamlit run frontend/app.py
(with the backend already running: uvicorn backend.main:app --reload)
"""

import os
import time

import requests
import streamlit as st
import streamlit.components.v1 as components

from frontend.render import dag_html, lecture_html

API = os.getenv("LECGAP_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="LecGap", layout="wide")

st.title("LecGap")
st.caption("Lecture Comprehension Gap Detector")


def _get(path: str, params=None, timeout: int = 30, silent: bool = False):
    """Error-safe GET — network/timeout failures and 4xx/5xx become an
    on-screen note instead of a traceback wall (F-10 in the audit)."""
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.Timeout:
        if not silent:
            st.error(f"Request to {path} timed out after {timeout}s.")
    except requests.RequestException as exc:
        if not silent:
            st.error(f"Backend request failed ({exc.__class__.__name__}): {exc}")
    except Exception as exc:  # noqa: BLE001 — JSON shape errors surface neatly
        if not silent:
            st.error(f"Could not read {path}: {exc}")
    return None


def _post(path: str, json=None, files=None, data=None, timeout: int = 600):
    """Error-safe POST; 4xx/5xx bodies show the backend's `detail` text."""
    try:
        r = requests.post(
            f"{API}{path}", json=json, files=files, data=data, timeout=timeout
        )
    except requests.Timeout:
        st.error(f"Request to {path} timed out after {timeout}s — "
                 "the job may still be running; check the lecture progress bar.")
        return None
    except requests.RequestException as exc:
        st.error(f"Backend request failed ({exc.__class__.__name__}): {exc}")
        return None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        st.error(detail)
        return None
    return r.json()


def _delete(path: str):
    try:
        r = requests.delete(f"{API}{path}", timeout=30)
    except requests.RequestException as exc:
        st.error(f"Backend request failed ({exc.__class__.__name__}): {exc}")
        return None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        st.error(detail)
        return None
    return r.json()


def _course_options():
    """Active courses from GET /courses summaries; /lectures as a fallback."""
    summaries = _get("/courses", silent=True)
    if summaries:
        return sorted({c["course_id"] for c in summaries})
    lectures = _get("/lectures", silent=True) or []
    return sorted({l["course_id"] for l in lectures})


def _wrap_progress(pbar, pct, text):
    try:
        pbar.progress(min(int(pct), 100), text=text)
    except TypeError:  # older streamlit: no `text` kwarg
        pbar.progress(min(int(pct), 100))
        st.caption(text)


def _wait_progress(lecture_id: int, timeout: int = 6 * 60 * 60):
    """Poll GET /lectures/{id}/progress until a background job settles.

    Returns the final payload (status ready/error) or None on timeout. Shows a
    live progress bar + stage message while it spins (the F-4/C-1 wiring).
    """
    pbar = st.progress(0)
    box = st.empty()
    started = time.monotonic()
    seen = set()
    while True:
        data = _get(f"/lectures/{lecture_id}/progress", silent=True)
        if data:
            status = data.get("status", "")
            pct = data.get("progress_pct", 0)
            detail = data.get("detail", "")
            if status == "ready":
                pbar.progress(100)
                box.success(detail or "Done.")
                return data
            if status in ("error", "not_found"):
                pbar.progress(0)
                box.error(detail or f"Job ended with status '{status}'.")
                return data
            _wrap_progress(pbar, pct, detail or status)
        else:
            box.warning("Job queued — waiting for the worker to report progress...")
        if time.monotonic() - started > timeout:
            box.warning("Timed out waiting; the job is still running in the "
                        "background — you can reload the page to check.")
            return None
        time.sleep(1.0)


# ------------------------------------------------------------------- sidebar

with st.sidebar:
    st.subheader("Course")
    courses = _course_options()
    if "nav_course" not in st.session_state and courses:
        st.session_state.nav_course = courses[0]
    if courses:
        nav_course = st.selectbox(
            "Active course", courses, key="nav_course",
            help="All tabs operate on this course.",
        )
        summary = {c["course_id"]: c for c in (_get("/courses", silent=True) or [])}
        row = summary.get(nav_course)
        if row:
            st.caption(
                f"{row['total_lectures']} lectures · {row['ready_lectures']} ready · "
                f"{row['total_concepts']} concepts · "
                f"{'graph ✓' if row['has_graph'] else 'no graph yet'}"
            )
        if st.button("Refresh course list"):
            try:
                st.rerun()
            except AttributeError:
                st.experimental_rerun()
        with st.expander("Delete this course", expanded=False):
            st.caption("Removes lectures, graph, quiz rows, media and clips.")
            confirm = st.checkbox("Yes, delete all data for this course")
            if st.button("Delete", disabled=not confirm):
                res = _delete(f"/courses/{nav_course}")
                if res:
                    st.success(res.get("message", "Course deleted."))
                    st.session_state.pop("nav_course", None)
                    try:
                        st.rerun()
                    except AttributeError:
                        st.experimental_rerun()
    else:
        nav_course = st.selectbox("Active course", ["ml1"], key="nav_course")
        st.caption("No courses yet — upload a lecture to begin.")


tab_student, tab_faculty = st.tabs(["Student", "Faculty"])

# --------------------------------------------------------------- student tab

with tab_student:
    st.subheader("Ingest a lecture")
    with st.form("upload_form"):
        course_id = st.text_input("Course ID", value=nav_course)
        title = st.text_input("Title (optional)", value="", placeholder="Auto = filename")
        backend = st.selectbox(
            "Transcription backend",
            ["auto", "local", "groq"],
            help="auto: groq when GROQ_API_KEY + ffmpeg are available (≈10× "
                 "real-time live-measured), otherwise the bundled local Whisper.",
        )
        up = st.file_uploader("Lecture media (mp4/mp3/wav/m4a/mkv/mov/webm)")
        submit = st.form_submit_button("Upload + transcribe")
    if submit and up:
        data = {"course_id": course_id.strip()}
        if title.strip():
            data["title"] = title.strip()
        if backend != "auto":
            data["whisper_backend"] = backend
        resp = _post(
            "/lectures",
            files={"file": (up.name, up.getvalue(), "application/octet-stream")},
            data=data,
        )
        if resp:
            st.success(f"Uploaded lecture #{resp['id']} — transcribing now.")
            _wait_progress(resp["id"])

    st.divider()
    st.subheader("Process a lecture")
    st.caption("Extract concepts → auto-rebuild the course graph → cut clips.")

    lectures = _get("/lectures", silent=True) or []
    ready = [
        l for l in lectures
        if l.get("course_id") == nav_course and l.get("status") == "ready"
    ]

    def _label(l):
        return f"#{l['id']} — {l.get('title', l.get('course_id'))}"

    if not ready:
        st.warning(f"No ready lecture in course '{nav_course}' — upload one above.")
    else:
        chosen = st.selectbox("Lecture to process", ready, format_func=_label)
        if st.button("Extract concepts + build graph"):
            resp = _post(f"/lectures/{chosen['id']}/concepts")
            if resp:
                st.success(f"Extraction queued for #{chosen['id']} — the course "
                           "graph rebuilds automatically once concepts land.")
                _wait_progress(chosen["id"])
        if st.button("Rebuild graph only (after edits/reruns)"):
            resp = _post(f"/courses/{nav_course}/graph")
            if resp:
                st.success(f"Graph build queued for '{nav_course}'.")
                _wait_progress(chosen["id"])
        if st.button("Cut concept clips"):
            resp = _post(f"/lectures/{chosen['id']}/clips")
            if resp:
                st.success(f"Clip cutting queued for #{chosen['id']}.")
                _wait_progress(chosen["id"])
                batch = _get(f"/lectures/{chosen['id']}/clips", silent=True) or {}
                ok = [c for c in batch.get("clips", []) if c.get("ok")]
                st.write(f"{len(ok)} clips cut under "
                         f"data/processed/clips/{chosen['id']}/")
                if ok:
                    with st.expander("Clip file paths"):
                        for c in ok:
                            st.code(c.get("path", ""))

    st.divider()
    st.subheader("Take the quiz")

    with st.form("quiz_form"):
        student_id = st.text_input("Student ID", value="demo-student")
        take = st.form_submit_button("Generate quiz")
    if take:
        quiz = _post("/quizzes", json={"course_id": nav_course,
                                       "student_id": student_id})
    else:
        quiz = None

    if quiz:
        with st.form("answers_form"):
            answers = []
            for q in quiz["questions"]:
                options = q.get("options") or ["correct", "incorrect"]
                ans = st.radio(
                    f"{q['question']}",
                    options=options,
                    key=f"q{q['id']}",
                )
                answers.append(
                    {"question_id": q["id"], "selected": ans,
                     "latency_s": 2.0}
                )
            done = st.form_submit_button("Submit answers")
        if done:
            result = _post(
                "/quizzes/submit",
                json={"course_id": nav_course, "student_id": student_id,
                      "answers": answers},
            )
            if result:
                st.write(f"Score: {result['score']}/{result['total']}")
                st.markdown("### Feedback (per question)")
                for f in result.get("feedback", []):
                    tag = "correct" if f["correct"] else "wrong"
                    st.write(f"**{f['concept']}** — _{tag}_")
                    if f.get("explanation"):
                        st.write(f"- ✓ {f['explanation']}")
                    if not f["correct"]:
                        if f.get("answer"):
                            st.write(f"- ✓ correct answer: {f['answer']}")
                        if f.get("rationale"):
                            st.write(f"- ✗ why your pick was wrong: {f['rationale']}")
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
        view = st.form_submit_button("Load course stats")
    if view and nav_course:
        stats = _get("/courses/" + nav_course + "/stats")
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

    st.divider()
    st.subheader("Concept prerequisite DAG")
    st.caption("Topological (learner) order runs top→bottom; hover a node for its "
               "rank in the sequence, hover an edge for the confidence + where the "
               "link came from (spoken transcript vs classifier) + its evidence. "
               "Early concepts are teal, late ones coral.")
    with st.form("dag_form"):
        show_dag = st.form_submit_button("Render DAG")
    if show_dag and nav_course:
        graph = _get("/courses/" + nav_course + "/graph")
        if graph and graph.get("nodes"):
            st.write(f"**{graph['node_count']} nodes · {graph['edge_count']} edges · "
                     f"{'acyclic (DAG)' if graph['is_dag'] else 'has cycles'}**")
            components.html(dag_html(graph), height=760, scrolling=True)
            with st.expander("Learner order (topological)"):
                for i, name in enumerate(graph.get("topological_order", []), 1):
                    st.write(f"{i}. {name}")
        elif graph:
            st.info("No nodes yet — run 'Extract concepts + build graph' from the "
                    "Student tab.")

    st.divider()
    st.subheader("Lecture timeline & coverage")
    st.caption("How much of the spoken lecture the extracted concepts actually pin "
               "down (green = covered window), with each concept's quiz-answer "
               "evidence sentence. Pick any ready lecture in the course.")
    ready_tl = [
        l for l in lectures
        if l.get("course_id") == nav_course and l.get("status") == "ready"
    ]
    if not ready_tl:
        st.info(f"No ready lecture in course '{nav_course}' yet.")
    else:
        tl_pick = st.selectbox("Lecture", ready_tl, format_func=_label,
                               key="tl_lecture")
        detail = _get(f"/lectures/{tl_pick['id']}", silent=True)
        if detail:
            components.html(
                lecture_html(
                    detail.get("segments", []),
                    detail.get("concepts", []),
                    lecture_title=f"{nav_course} — {detail.get('title', '')}",
                ),
                height=520 + 24 * len(detail.get("concepts", [])),
                scrolling=True,
            )