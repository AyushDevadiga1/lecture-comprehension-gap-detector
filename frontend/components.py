"""Shared Streamlit UI for the two LecGap dashboards.

Holds the browser-facing building blocks that BOTH entrypoints use: the course
sidebar, the live background-job monitor (multi-job, replaces the single-slot
``lecgap_job``), and the student quiz flow (persisted in Tier-2 session state so
background-job reruns can never wipe it). Everything reads through
``frontend.client`` / ``frontend.render`` / ``frontend.state``.

The entrypoints (``student_app.py``, ``faculty_app.py``) stay thin: they wire
widgets and call the functions here.
"""

import time

import streamlit as st

from frontend import client, state
from frontend.render import dag_html, lecture_html

_MAX_POLL_FAILS = 5
_JOB_DEADLINE_S = 6 * 60 * 60

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


# ------------------------------------------------------------------ sidebar

def course_sidebar():
    """Render the shared course picker + summary + delete. Returns the active
    course id (or None when there are no courses). Reads/locks the selection
    through the ``nav_course`` widget so both dashboards behave identically."""
    courses = _course_options()
    if "nav_course" not in st.session_state and courses:
        st.session_state.nav_course = courses[0]

    if not courses:
        st.selectbox("Active course", ["ml1"], disabled=True,
                     key="nav_course")
        st.caption("No courses yet — upload a lecture to begin.")
        return None

    nav_course = st.selectbox(
        "Active course", courses, key="nav_course",
        help="All actions on this dashboard operate on this course.",
    )
    summaries = {c["course_id"]: c for c in (client.course_summaries() or [])}
    row = summaries.get(nav_course)
    if row:
        st.caption(
            f"{row['total_lectures']} lectures · {row['ready_lectures']} ready · "
            f"{row['total_concepts']} concepts · "
            f"{'graph ✓' if row['has_graph'] else 'no graph yet'}"
        )
    if st.button("Refresh course list"):
        client.invalidate_all()
        _rerun()
    with st.expander("Delete this course", expanded=False):
        st.caption("Removes lectures, graph, quiz rows, media and clips.")
        confirm = st.checkbox("Yes, delete all data for this course")
        if st.button("Delete", disabled=not confirm):
            res = client.delete(f"/courses/{nav_course}")
            if res:
                st.success(res.get("message", "Course deleted."))
                client.invalidate_all()
                st.session_state.pop("nav_course", None)
                _rerun()
    return nav_course


def _rerun():
    try:
        st.rerun()
    except Exception:  # noqa: BLE001 - test/bare runtimes
        pass


def _course_options():
    """Active courses from GET /courses summaries; /lectures as fallback."""
    summaries = client.course_summaries()
    if summaries:
        return sorted({c["course_id"] for c in summaries})
    lectures = client.list_lectures() or []
    return sorted({l["course_id"] for l in lectures})


# ------------------------------------------------------------ auth / banners

def render_auth_banner():
    """One top-level notice when the backend rejected us for auth, instead of
    the old silent 'No courses yet' degradation (audit fix #4)."""
    err = client.take_last_error()
    if err and err["kind"] == "auth":
        st.error("Backend requires an API key — set LECGAP_API_KEY on the "
                 "frontend to match the backend, then refresh.")
    # a non-auth recorded error is left in place for callers to surface.


# ------------------------------------------------------------------ jobs

def start_job(course_id, lecture_id, title, kind, after=None):
    """Remember a background job so the monitor renders its card on the next
    rerun. Jobs accumulate — starting a new one never drops an old card
    (audit fix #6). Identical (lecture, kind) pairs are coalesced."""
    items = state.get("jobs", "items", [])
    items = [
        j for j in items
        if not (j.get("course_id") == course_id
                and j.get("lecture_id") == lecture_id
                and j.get("kind") == kind)
    ]
    items.append({
        "course_id": course_id,
        "lecture_id": lecture_id,
        "title": title,
        "kind": kind,
        "after": after,
        "fail_count": 0,
        "deadline": time.monotonic() + _JOB_DEADLINE_S,
    })
    state.set("jobs", items=items)


def _job_guidance(stage, elapsed_s):
    hint = _STAGE_HINTS.get(stage, f"Currently: {stage or 'working'}.")
    mm, ss = divmod(int(elapsed_s or 0), 60)
    return f"{hint}  Elapsed: {mm}m {ss:02d}s"


def render_progress_cards():
    """Live, self-refreshing progress card per monitored job.

    One poll per rerun, adaptive back-off (fast on short stages, slower on long
    unadvancing ones). Jobs are removed once terminal; a follow-up (e.g. the
    clip list) runs straight after ``ready``.
    """
    items = state.get("jobs", "items", []) or []
    if not items:
        return

    keep, want_rerun, backoff = [], False, 1.5
    for job in items:
        lecture_id = job.get("lecture_id")
        data = client.get(f"/lectures/{lecture_id}/progress")
        if not data:
            fails = int(job.get("fail_count", 0)) + 1
            job["fail_count"] = fails
            if fails < _MAX_POLL_FAILS:
                keep.append(job)
                want_rerun = True
                continue
            st.warning(f"Job '{job.get('title', '')}' is queued but unreachable — "
                       "the worker may have stopped. Refresh to re-attach.")
            continue

        job["fail_count"] = 0
        status = data.get("status", "")
        stage = data.get("stage", "working")

        if status == "ready":
            st.progress(100)
            st.success(data.get("detail") or f"{job.get('title')} — Done.")
            client.invalidate_for_course(job.get("course_id"))
            _run_after(job, lecture_id)
            continue
        if status in ("error", "not_found"):
            st.error(data.get("detail") or f"Job ended with status '{status}'.")
            client.invalidate_for_course(job.get("course_id"))
            continue

        st.progress(min(int(data.get("progress_pct", 0)), 100),
                    text=data.get("detail") or stage)
        st.caption(_job_guidance(stage, data.get("elapsed_s", 0)))

        if time.monotonic() > float(job.get("deadline", 0)):
            st.warning("Timed out waiting — the job still runs in the "
                       "background; reload to re-attach.")
            continue
        keep.append(job)
        want_rerun = True
        backoff = min(backoff, 1.5 if stage in _LONG_STAGES else 0.5)

    state.set("jobs", items=keep)
    if want_rerun:
        time.sleep(backoff)
        try:
            st.rerun()
        except Exception:  # noqa: BLE001 - AppTest / bare runtimes have no rerun
            pass


def _run_after(job, lecture_id):
    if job.get("after") == "clips_list":
        batch = client.get(f"/lectures/{lecture_id}/clips") or {}
        ok = [c for c in batch.get("clips", []) if c.get("ok")]
        st.write(f"{len(ok)} clips cut under "
                 f"data/processed/clips/{lecture_id}/")
        if ok:
            with st.expander("Clip file paths"):
                for c in ok:
                    st.code(c.get("path", ""))


def attach_in_flight_jobs(course_id):
    """Transparency between users: if the current session has no monitored job
    but the course has lectures stuck in a non-ready state, surface them as
    monitor cards so a fresh tab sees what the backend is doing."""
    if state.get("jobs", "items"):
        return
    lectures = client.list_lectures() or []
    in_flight = [
        l for l in lectures
        if l.get("course_id") == course_id and l.get("status") not in ("ready", "error")
    ]
    for lec in in_flight:
        start_job(course_id, lec["id"], f"Lecture #{lec['id']} — {lec.get('status')}",
                  kind="attach")


def lecture_label(l):
    return f"#{l['id']} — {l.get('title', l.get('course_id'))}"


def ready_lectures(nav_course):
    lectures = client.list_lectures() or []
    return [
        l for l in lectures
        if l.get("course_id") == nav_course and l.get("status") == "ready"
    ]


# ------------------------------------------------------------------ quiz

def render_quiz(nav_course):
    """Student quiz flow with Tier-2 persistence.

    The generated questions live in ``state['quiz']`` (not a function local), so
    the background-job monitor re-running the script cannot wipe a student's
    in-flight quiz (audit fix #1). A submit 404 (server regenerated the course's
    questions) degrades to a clear 'generate again' instead of a traceback
    (fix #9).
    """
    st.subheader("Take the quiz")

    if "quiz_student_id" not in st.session_state:
        st.session_state.quiz_student_id = state.get("quiz", "student_id", "demo-student")
    student_id = st.text_input("Student ID", key="quiz_student_id")

    if st.button("Generate quiz"):
        state.set("quiz", course_id=nav_course, student_id=student_id,
                  questions=None, version=int(state.get("quiz", "version", 0)) + 1,
                  render_t=time.time(), result=None)
        quiz = client.post("/quizzes", json={"course_id": nav_course,
                                             "student_id": student_id})
        err = client.take_last_error()
        if quiz and quiz.get("questions"):
            state.set("quiz", questions=quiz["questions"],
                      render_t=time.time(), result=None)
        elif err:
            st.error(err.get("detail") or "Quiz generation failed.")

    questions = state.get("quiz", "questions")
    stale_course = state.get("quiz", "course_id") != nav_course
    if not questions or stale_course:
        if stale_course:
            state.clear("quiz")
        return

    with st.form("answers_form"):
        answers = []
        for q in questions:
            options = q.get("options") or ["correct", "incorrect", "wrong"]
            ans = st.radio(
                f"{q['question']}", options=options, key=f"legap_q{q['id']}",
            )
            answers.append({"question_id": q["id"], "selected": ans,
                            "latency_s": None})
        done = st.form_submit_button("Submit answers")

    if done:
        render_t = state.get("quiz", "render_t")
        if render_t:
            per_q = round((time.time() - render_t) / max(len(answers), 1), 2)
            for a in answers:
                a["latency_s"] = per_q
        result = client.post(
            "/quizzes/submit",
            json={"course_id": nav_course, "student_id": student_id,
                  "answers": answers},
        )
        err = client.take_last_error()
        if result:
            state.set("quiz", result=result)
            state.set("quiz", questions=None)  # one shot: don't re-submit stale ids
        elif err and err.get("status") == 404:
            st.error("The quiz on the server was regenerated while you were "
                     "answering — please generate the quiz again.")
            state.set("quiz", questions=None, result=None)
        else:
            st.error((err or {}).get("detail") or "Submit failed — try again.")

    result = state.get("quiz", "result")
    if result:
        _render_result(nav_course, result, student_id)


def _render_result(nav_course, result, student_id):
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
        url = client.media_url(item.get("clip"))
        if url:
            st.video(url)


# ------------------------------------------------------------------- faculty

def render_faculty_stats(nav_course):
    st.subheader("Confusion heatmap + taught-vs-learned divergence")

    if st.button("Load course stats"):
        data = client.course_stats(nav_course)
        if data:
            state.set("faculty", stats=data, stats_course=nav_course)
    stats = state.get("faculty", "stats")
    if stats and state.get("faculty", "stats_course") == nav_course:
        st.markdown("**Wrong-answer rates (highest first):**")
        for h in stats.get("heatmap", []):
            st.write(f"- {h['concept']}: {h['wrong']}/{h['attempts']} "
                     f"({h['rate']:.0%})")
        st.markdown("**Taught order → learned order divergence:**")
        for d in stats.get("divergence", []):
            delta = d.get("gap", 0)
            arrow = "→ later" if delta > 0 else ("← earlier" if delta < 0 else "=")
            ti = d.get("taught_idx")
            li = d.get("learned_idx")
            st.write(f"- {d['concept']}: taught #{ti if ti is not None else '—'} "
                     f"vs learned #{li if li is not None else '—'} ({arrow})")


def render_faculty_dag(nav_course):
    st.subheader("Concept prerequisite DAG")
    st.caption("Topological (learner) order runs top→bottom; hover a node for its "
               "rank in the sequence, hover an edge for the confidence + where the "
               "link came from (spoken transcript vs classifier) + its evidence. "
               "Early concepts are teal, late ones coral.")
    if st.button("Render DAG"):
        graph = client.course_graph(nav_course)
        if graph is not None:
            state.set("faculty", graph=graph, graph_course=nav_course)
    graph = state.get("faculty", "graph")
    if graph and state.get("faculty", "graph_course") == nav_course:
        if graph.get("nodes"):
            st.write(f"**{graph['node_count']} nodes · {graph['edge_count']} edges · "
                     f"{'acyclic (DAG)' if graph['is_dag'] else 'has cycles'}**")
            st.iframe(dag_html(graph), height=760)
            with st.expander("Learner order (topological)"):
                for i, name in enumerate(graph.get("topological_order", []), 1):
                    st.write(f"{i}. {name}")
        else:
            st.info("No nodes yet — run 'Extract concepts + build graph' from the "
                    "Student dashboard.")


def render_faculty_timeline(nav_course):
    st.subheader("Lecture timeline & coverage")
    st.caption("How much of the spoken lecture the extracted concepts actually pin "
               "down (green = covered window), with each concept's quiz-answer "
               "evidence sentence. Pick any ready lecture in the course.")
    ready = ready_lectures(nav_course)
    if not ready:
        st.info(f"No ready lecture in course '{nav_course}' yet.")
        return
    pick = st.selectbox("Lecture", ready, format_func=lecture_label,
                        key="tl_lecture")
    state.set("tl", lecture_id=pick["id"])
    detail = client.lecture_detail(pick["id"])
    if detail:
        st.iframe(
            lecture_html(
                detail.get("segments", []),
                detail.get("concepts", []),
                lecture_title=f"{nav_course} — {detail.get('title', '')}",
            ),
            height=520 + 24 * len(detail.get("concepts", [])),
        )