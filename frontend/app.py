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
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components

from frontend.render import dag_html, lecture_html

_DEFAULT_API = "http://127.0.0.1:8000"
# Consecutive failed progress polls tolerated before a job is considered
# unreachable and polling stops (SECURITY_AUDIT #29).
_MAX_POLL_FAILS = 5


def _validated_api_url(raw: str) -> str:
    """Validate the backend base URL (SECURITY_AUDIT #25).

    Only http/https URLs with a host are accepted: a file:///ftp:// or host-less
    value could otherwise redirect backend calls at a local resource.
    """
    url = (raw or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(
            f"LECGAP_API_URL must be an http(s) URL with a host, got {raw!r}"
        )
    return url


API = _validated_api_url(os.getenv("LECGAP_API_URL", _DEFAULT_API))

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


def _post(path: str, json=None, files=None, data=None, params=None, timeout: int = 600):
    """Error-safe POST; 4xx/5xx bodies show the backend's `detail` text."""
    try:
        r = requests.post(
            f"{API}{path}", json=json, files=files, data=data,
            params=params, timeout=timeout,
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


@st.cache_data(ttl=60)
def _course_summaries():
    """GET /courses summaries, memoized so sidebar reruns don't re-hit the API
    (M4). Call `.clear()` after an upload/delete that changes the course list."""
    return _get("/courses", silent=True)


@st.cache_data(ttl=60)
def _list_lectures():
    """GET /lectures, memoized like the course summaries. The student tab
    re-reads the lecture list on EVERY streamlit rerun (it renders the
    selectboxes + ready-lecture filters), so this was the single biggest
    repeat HTTP cost. Cleared whenever lecture/status data can change:
    upload, job completion, delete, refresh button."""
    return _get("/lectures", silent=True) or []


@st.cache_data(ttl=300, show_spinner=False)
def _lecture_detail(lecture_id: int):
    """GET /lectures/{id} (segments + concepts) for the faculty timeline.
    Cached because Streamlit executes EVERY tab body on every rerun, so an
    uncached detail fetch would re-parse the whole transcript each interaction
    even while the user is on the Student tab."""
    return _get(f"/lectures/{lecture_id}", silent=True)


def _invalidate_data_caches():
    """Drop the course/lecture caches after any action that can change them."""
    for fn in (_course_summaries, _list_lectures, _lecture_detail):
        try:
            fn.clear()
        except AttributeError:
            pass


def _course_options():
    """Active courses from GET /courses summaries; /lectures as a fallback."""
    summaries = _course_summaries()
    if summaries:
        return sorted({c["course_id"] for c in summaries})
    lectures = _get("/lectures", silent=True) or []
    return sorted({l["course_id"] for l in lectures})


# Stage -> guidance shown under the live progress bar. Long stages that cannot
# report finer granularity (local Whisper decode, parallel clip cutting) get an
# honest "the bar sits here until this finishes" hint instead of a false sense
# of progress.
_STAGE_HINTS = {
    "initializing": "Starting the background job…",
    "probing": "Probing audio duration with ffprobe…",
    "downmixing": "Normalizing audio to 16 kHz mono FLAC…",
    "loading_model": "Whisper model loading (one-time, ~1 min on CPU)…",
    "chunking": "Slicing audio into API-sized chunks…",
    "transcribing": "Hosted Whisper is transcribing — usually a few minutes "
                    "for a full lecture.",
    "local_transcribing": "CPU Whisper decodes at roughly real-time: a 1-hour "
                          "lecture takes ~45–90 min and this bar stays put "
                          "until it finishes. Leave the page open; you can "
                          "refresh anytime to re-attach.",
    "finalizing": "Finalizing timestamps…",
    "saving_segments": "Saving transcript segments to the database…",
    "extracting": "Reading the lecture structure (passages, concepts, spoken "
                  "prerequisite links)…",
    "building_graph": "Deduplicating concepts and scoring prerequisite edges…",
    "clips": "Cutting concept clips with ffmpeg (re-encoded, several minutes "
             "for many clips)…",
    "saving_clips": "Saving clip rows…",
}

_LONG_STAGES = {
    "local_transcribing", "building_graph", "clips", "saving_clips", "extracting",
}


def _job_guidance(stage: str, elapsed_s: float) -> str:
    """One-line explanation of what the current stage is doing + elapsed time."""
    hint = _STAGE_HINTS.get(stage, f"Currently: {stage or 'working'}.")
    mm, ss = divmod(int(elapsed_s or 0), 60)
    return f"{hint}  Elapsed: {mm}m {ss:02d}s"


def _monitor_progress():
    """Live, self-refreshing progress card for the most recent background job.

    One poll per rerun, re-render the card, then `st.rerun()` with an
    adaptive back-off: fast during short stages, slower during long ones.
    (Replaces the old blocking poll loop, whose `st.progress` spin froze the
    whole Streamlit session for the entire transcribe/extract.)

    Poll cadence is never hardcoded to 1s (L9): long stages that can't advance
    (local Whisper decode, clip re-encode, graph build) back off to ~2s so a
    single open tab doesn't hammer /lectures/{id}/progress.
    """
    job = st.session_state.get("lecgap_job")
    if not job:
        return
    lecture_id = job.get("lecture_id")
    data = _get(f"/lectures/{lecture_id}/progress", silent=True)
    if not data:
        # Tolerate a few transient blips before giving up, so a momentary
        # backend hiccup doesn't strand the monitor (SECURITY_AUDIT #29).
        fails = int(job.get("fail_count", 0)) + 1
        job["fail_count"] = fails
        if fails < _MAX_POLL_FAILS:
            time.sleep(1.0)
            try:
                st.rerun()
            except AttributeError:
                pass
            return
        st.warning("Job queued — waiting for the worker to report progress... "
                   "You can refresh the page to re-attach.")
        st.session_state.pop("lecgap_job", None)
        return
    job["fail_count"] = 0

    status = data.get("status", "")
    stage = data.get("stage", "working")
    pct = data.get("progress_pct", 0)
    detail = data.get("detail", "")
    elapsed = data.get("elapsed_s", 0)

    if status == "ready":
        st.progress(100)
        st.success(detail or "Done.")
        _invalidate_data_caches()
        after = job.get("after")
        lecture_id_for_clips = lecture_id
        st.session_state.pop("lecgap_job", None)
        if after == "clips_list":
            batch = _get(f"/lectures/{lecture_id_for_clips}/clips", silent=True) or {}
            ok = [c for c in batch.get("clips", []) if c.get("ok")]
            st.write(f"{len(ok)} clips cut under "
                     f"data/processed/clips/{lecture_id_for_clips}/")
            if ok:
                with st.expander("Clip file paths"):
                    for c in ok:
                        st.code(c.get("path", ""))
        return
    if status in ("error", "not_found"):
        st.error(detail or f"Job ended with status '{status}'.")
        _invalidate_data_caches()
        st.session_state.pop("lecgap_job", None)
        return

    st.progress(min(int(pct), 100), text=detail or stage)
    st.caption(_job_guidance(stage, elapsed))

    deadline = job.get("deadline", time.monotonic() + 6 * 60 * 60)
    if time.monotonic() > deadline:
        st.warning("Timed out waiting; the job still runs in the background — "
                   "you can reload the page to re-attach.")
        st.session_state.pop("lecgap_job", None)
        return

    # Short stages tick quickly; poll cadence adapts to what is running.
    # Long stages that can't advance (local Whisper decode, clip re-encode,
    # graph build, extraction) back off so one open tab doesn't hammer the API.
    time.sleep(1.5 if stage in _LONG_STAGES else 0.5)
    try:
        st.rerun()
    except AttributeError:
        pass  # older streamlit (<1.28): no st.rerun, one poll per user action


def _start_job(lecture_id: int, title: str, after: str = None) -> None:
    """Remember a background job so `_monitor_progress` renders its card on the
    next rerun (upload/extract/graph/clips kickoffs). `after` runs a follow-up
    once the job lands on `ready` (e.g. listing freshly cut clips)."""
    st.session_state["lecgap_job"] = {
        "lecture_id": lecture_id,
        "title": title,
        "after": after,
        "deadline": time.monotonic() + 6 * 60 * 60,
    }


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
        summary = {c["course_id"]: c for c in (_course_summaries() or [])}
        row = summary.get(nav_course)
        if row:
            st.caption(
                f"{row['total_lectures']} lectures · {row['ready_lectures']} ready · "
                f"{row['total_concepts']} concepts · "
                f"{'graph ✓' if row['has_graph'] else 'no graph yet'}"
            )
        if st.button("Refresh course list"):
            _course_summaries.clear()
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


# ------------------------------------------------------- page render functions

def _lecture_label(l):
    return f"#{l['id']} — {l.get('title', l.get('course_id'))}"


def render_student_tab(nav_course):
    st.subheader("Ingest a lecture")
    _monitor_progress()

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
            _invalidate_data_caches()
            st.success(f"Uploaded lecture #{resp['id']} — transcribing now "
                       "(see the progress card below).")
            _start_job(resp["id"], "Transcription")

    st.divider()
    st.subheader("Process a lecture")
    st.caption("Extract concepts → auto-rebuild the course graph → cut clips.")

    lectures = _list_lectures()
    ready = [
        l for l in lectures
        if l.get("course_id") == nav_course and l.get("status") == "ready"
    ]

    if not ready:
        st.warning(f"No ready lecture in course '{nav_course}' — upload one above.")
    else:
        chosen = st.selectbox("Lecture to process", ready, format_func=_lecture_label)
        if st.button("Extract concepts + build graph"):
            resp = _post(f"/lectures/{chosen['id']}/concepts")
            if resp:
                st.success(f"Extraction queued for #{chosen['id']} — the course "
                           "graph rebuilds automatically once concepts land "
                           "(see the progress card below).")
                _start_job(chosen["id"], "Concept extraction + graph")
        if st.button("Rebuild graph only (after edits/reruns)"):
            resp = _post(f"/courses/{nav_course}/graph",
                         params={"lecture_id": chosen["id"]})
            if resp:
                st.success(f"Graph build queued for '{nav_course}' "
                           "(see the progress card below).")
                _start_job(chosen["id"], "Course-graph rebuild")
        if st.button("Cut concept clips"):
            resp = _post(f"/lectures/{chosen['id']}/clips")
            if resp:
                st.success(f"Clip cutting queued for #{chosen['id']} "
                           "(see the progress card below).")
                _start_job(chosen["id"], "Clip cutting", after="clips_list")

    st.divider()
    st.subheader("Take the quiz")

    with st.form("quiz_form"):
        student_id = st.text_input("Student ID", value="demo-student")
        take = st.form_submit_button("Generate quiz")
    if take:
        st.session_state["quiz_render_t"] = time.time()
        quiz = _post("/quizzes", json={"course_id": nav_course,
                                       "student_id": student_id})
    else:
        quiz = None

    if quiz:
        with st.form("answers_form"):
            answers = []
            for q in quiz["questions"]:
                options = q.get("options") or ["correct", "incorrect", "wrong"]
                ans = st.radio(
                    f"{q['question']}",
                    options=options,
                    key=f"q{q['id']}",
                )
                answers.append(
                    {"question_id": q["id"], "selected": ans,
                     "latency_s": None}
                )
            done = st.form_submit_button("Submit answers")
        if done:
            render_t = st.session_state.pop("quiz_render_t", None)
            if render_t is not None:
                # Real per-question attempt time (seconds), proxied as the
                # wall time from quiz render to submit / question count.
                per_q = round((time.time() - render_t) / max(len(answers), 1), 2)
                for a in answers:
                    a["latency_s"] = per_q
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

def render_faculty_tab(nav_course):
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
    lectures = _list_lectures()
    ready_tl = [
        l for l in lectures
        if l.get("course_id") == nav_course and l.get("status") == "ready"
    ]
    if not ready_tl:
        st.info(f"No ready lecture in course '{nav_course}' yet.")
    else:
        tl_pick = st.selectbox("Lecture", ready_tl, format_func=_lecture_label,
                               key="tl_lecture")
        detail = _lecture_detail(tl_pick["id"])
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


tab_student, tab_faculty = st.tabs(["Student", "Faculty"])

with tab_student:
    render_student_tab(nav_course)

with tab_faculty:
    render_faculty_tab(nav_course)