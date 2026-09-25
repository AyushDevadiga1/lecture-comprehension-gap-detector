"""Shared Streamlit UI for the two LecGap dashboards.

Holds the browser-facing building blocks that BOTH entrypoints use: the course
sidebar, the live background-job monitor (multi-job, replaces the single-slot
``lecgap_job``), and the student quiz flow (persisted in Tier-2 session state so
background-job reruns can never wipe it). Everything reads through
``frontend.client`` / ``frontend.render`` / ``frontend.state``.

The entrypoints (``student_app.py``, ``faculty_app.py``) stay thin: they wire
widgets and call the functions here.
"""

import threading
import time

import streamlit as st

from frontend import client, state
from frontend.render import dag_html, lecture_html

_MAX_POLL_FAILS = 5
_JOB_DEADLINE_S = 6 * 60 * 60

# In-process upload registry keyed by lecture id — survives reruns (module-level)
# so a background upload thread is never lost between script executions.
_UPLOADS = {}

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
        snap = client.course_snapshot(nav_course) or {}
        st.caption(f"Course key: `{nav_course}` · {_snapshot_line(snap)}")
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


# ------------------------------------------------------------ API quota row

def _usage_summary(services: dict, availability=None, duration_s=None) -> list:
    """Compose the quota transparency lines (pure, unit-testable)."""
    services = services or {}
    availability = availability or {}
    chat = services.get("groq.chat", {}) or {}
    whisper = services.get("groq.whisper", {}) or {}
    local = services.get("local", {}) or {}
    ollama = services.get("ollama", {}) or {}
    out = []

    def _has_data(s):
        return (s.get("calls", 0) or 0) > 0 or s.get("remaining_requests") is not None

    def _groq_line(name, s, has_tokens=False):
        reqs = s.get("remaining_requests")
        reset = s.get("reset_in_s")
        line = f"{name}: {reqs:,} req left"
        if has_tokens and s.get("remaining_tokens") is not None:
            line += f" · {s['remaining_tokens']:,} tok left"
        if reset is not None:
            mm = int(reset) // 60
            ss = int(reset) % 60
            line += f" · resets ~{mm}m{ss:02d}s"
        return line

    if _has_data(chat):
        out.append(_groq_line("Groq chat", chat, has_tokens=True))
    elif availability.get("groq_configured"):
        out.append("Groq chat: no usage data yet — appears after the first API call")
    if _has_data(whisper):
        out.append(_groq_line("Groq whisper", whisper))
    elif availability.get("groq_configured"):
        out.append("Groq whisper: no usage data yet — appears after the first API call")
    if local.get("available"):
        ff = "ffmpeg ✓" if local.get("ffmpeg_ok") else "ffmpeg ✗ (use local backend)"
        out.append(f"Local Whisper: available · offline · unlimited · {ff}")
    if ollama.get("reachable"):
        out.append("Ollama: reachable")

    if duration_s and _has_data(whisper) and whisper.get("remaining_requests") is not None:
        per = client.whisper_requests_for(duration_s)
        left = client.videos_left(whisper["remaining_requests"], duration_s)
        if left is not None and per:
            pct = per / max(whisper["remaining_requests"], 1) * 100
            plural = "s" if left != 1 else ""
            out.append(f"This lecture ≈ {per} Groq requests "
                       f"({pct:.1f}% of remaining) ≈ {left} more lecture{plural} like this.")
    return out


def render_usage_row():
    """Live per-service quota line(s) above the upload form (plan 10).

    Honest by design: services with no recorded call yet render 'no usage data
    yet' (never fake zeros); the per-lecture estimate uses the probed duration
    of the current transcribe job, so it is accurate as soon as ffprobe runs.
    """
    data = client.usage()
    if not data:
        return
    lines = _usage_summary(
        data.get("services"), availability=data.get("availability"),
        duration_s=_active_transcribe_duration(),
    )
    if lines:
        st.caption("API quota (live): " + " · ".join(lines))


def _active_transcribe_duration():
    """Duration of the first in-flight transcribe job (live, from progress)."""
    for job in (state.get("jobs", "items") or []):
        if job.get("kind") != "transcribe":
            continue
        data = client.get(f"/lectures/{job.get('lecture_id')}/progress")
        if data and data.get("duration_s"):
            return float(data["duration_s"])
    return None


def duplicate_lecture(course_id, filename):
    """Soft-warn (non-blocking) if a lecture for this course already uses this
    filename (title auto-defaults to the filename). Returns the lecture id or
    None."""
    if not filename:
        return None
    from pathlib import Path

    stem = Path(filename).stem
    for lec in (client.list_lectures() or []):
        if lec.get("course_id") != course_id:
            continue
        title = (lec.get("title") or "")
        if title == filename or title == stem or title == f"{stem}.":
            return lec["id"]
    return None


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


# ----------------------------------------------------------------- upload thread

def begin_upload(course_id, lecture_id, title, filename, file_bytes,
                 whisper_backend=None):
    """Non-blocking upload (plan §unch): create the row was already done; this
    streams the media in a daemon thread while the progress card shows the
    transfer, so the script never blocks on the file."""
    entry = _UPLOADS.get(lecture_id)
    if entry and not entry["done"].is_set():
        return False  # already uploading this lecture

    cancel = threading.Event()
    done = threading.Event()
    outcome = {"ok": False, "error": None}

    def worker():
        try:
            resp = client.upload_media(
                lecture_id, filename, file_bytes,
                whisper_backend=whisper_backend, cancel=cancel,
            )
            err = client.take_last_error()
            if resp is None:
                outcome["error"] = "Upload cancelled." if cancel.is_set() else (
                    (err or {}).get("detail") or "Upload failed."
                )
            outcome["ok"] = resp is not None
        except Exception as exc:  # noqa: BLE001 - surface in the card
            outcome["error"] = f"Upload failed: {exc}"
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    _UPLOADS[lecture_id] = {"thread": thread, "cancel": cancel, "done": done,
                            "ok": outcome, "title": title}
    thread.start()
    start_job(course_id, lecture_id, title, kind="upload")
    return True


def cancel_upload(lecture_id):
    entry = _UPLOADS.get(lecture_id)
    if entry and not entry["done"].is_set():
        entry["cancel"].set()
        return True
    return False


def _upload_status(lecture_id, kind):
    """(done, ok, error) for a job; ``(done=True, ok=True)`` once finished OK.

    ``done=False`` covers both "uploading" and "about to start" (registry entry
    pending) so the monitor keeps polling without inventing errors."""
    if kind != "upload":
        return None
    entry = _UPLOADS.get(lecture_id)
    if entry is None:
        return False, False, None  # awaiting the thread's first tick
    if entry["done"].is_set():
        _UPLOADS.pop(lecture_id, None)  # handled; keep memory tight
        return True, entry["ok"]["ok"], entry["ok"]["error"]
    return False, False, None


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
        kind = job.get("kind")

        # --- non-blocking upload: handle the client-side upload thread first ---
        if kind == "upload":
            pending, up_ok, up_err = _upload_status(lecture_id, kind)
            if not pending and not up_ok:
                st.error(up_err or "Upload failed.")
                client.invalidate_for_course(job.get("course_id"))
                continue
            if not pending:
                # hand off: media landed, the backend worker card reports from
                # here on (stage flips to transcribing after the PUT schedules it)
                job["kind"] = "transcribe"
                kind = "transcribe"
            elif st.button("Cancel upload", key=f"cancel_up_{lecture_id}"):
                cancel_upload(lecture_id)

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
        if kind == "upload" and status == "uploaded":
            st.progress(0, text="Upload starting…")
            st.caption(job.get("title", "Upload"))
            keep.append(job)
            want_rerun = True
            backoff = min(backoff, 0.5)
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


def _snapshot_line(data) -> str:
    """Compact readiness line from a /snapshot payload (pure, unit-testable)."""
    snap = data.get("lectures", {}) or {}
    graph = data.get("graph", {}) or {}
    clips = data.get("clips", {}) or {}
    quiz = data.get("quiz", {}) or {}
    return (f"{snap.get('total', 0)} lectures · {snap.get('ready', 0)} ready · "
            f"{data.get('concepts', 0)} concepts · "
            f"{'graph ✓' if graph.get('has') else 'no graph'} · "
            f"{clips.get('ok', 0)} clips ✓ · {quiz.get('questions', 0)} questions")


def render_course_snapshot(course_id):
    """Live course-readiness strip (plan §13): the 5s snapshot drives both
    dashboards, so a change made in one session surfaces in the other. Seeds
    monitor cards only for *transcribing* lectures (finding A1 fix: a stuck
    ``uploaded`` row is a hint, never a spinning card)."""
    if not course_id:
        return
    data = client.course_snapshot(course_id)
    if not data:
        return
    st.caption("Course readiness: " + _snapshot_line(data))

    in_flight = data.get("in_flight", []) or []
    uploading = [f for f in in_flight if f.get("status") == "uploaded"]
    transcribing = [f for f in in_flight if f.get("status") == "transcribing"]

    if transcribing:
        st.info("Processing in progress:")
        for f in transcribing:
            pro = client.get(f"/lectures/{f['lecture_id']}/progress") or {}
            st.text(f"  • #{f['lecture_id']} — {f.get('title')} "
                    f"[{pro.get('stage', f.get('stage', ''))} "
                    f"{pro.get('progress_pct', f.get('progress_pct', 0))}%]")
        _seed_monitor_from_snapshot(course_id, transcribing)

    if uploading:
        ids = ", ".join(str(f["lecture_id"]) for f in uploading)
        st.warning(f"{len(uploading)} lecture(s) awaiting media (uploaded but not "
                   f"streamed: #{ids}) — delete or re-upload them.")


def _seed_monitor_from_snapshot(course_id, transcribing):
    """Attach monitor cards for backend jobs a fresh tab wasn't present for.
    Only ``transcribing`` rows (never stuck ``uploaded`` rows — A1)."""
    already = {
        (j.get("course_id"), j.get("lecture_id"), j.get("kind"))
        for j in (state.get("jobs", "items") or [])
    }
    for f in transcribing:
        key = (course_id, f["lecture_id"], "attach")
        if key in already:
            continue
        start_job(course_id, f["lecture_id"],
                  f"Lecture #{f['lecture_id']} — {f.get('title')}", kind="attach")


def lecture_label(l):
    return f"#{l['id']} — {l.get('title', l.get('course_id'))}"


def render_lecture_rows(nav_course):
    """Manage / delete lecture rows (finding B3): failed or abandoned uploads
    (stuck in ``uploaded`` because the media never streamed, or ``error``) are
    otherwise unremovable — only whole-course delete existed. Checked rows are
    deleted via DELETE /lectures/{id}, then the course/lecture caches clear."""
    st.subheader("Lecture rows")
    st.caption("Remove failed or abandoned uploads (e.g. rows stuck in "
               "'uploaded' because the file never streamed).")
    lectures = client.list_lectures() or []
    rows = [l for l in lectures if l.get("course_id") == nav_course]
    if not rows:
        st.caption("No lecture rows for this course.")
        return

    wanted = [
        lec["id"] for lec in rows
        if st.checkbox(
            f"Delete #{lec['id']} — {lec.get('title')} ({lec.get('status')})",
            key=f"delrow_{lec['id']}",
        )
    ]

    if st.button("Delete checked rows", disabled=not wanted):
        deleted_any = False
        for lid in wanted:
            res = client.delete(f"/lectures/{lid}")
            if res:
                deleted_any = True
            else:
                err = client.take_last_error()
                st.error((err or {}).get("detail") or f"Delete lecture #{lid} failed.")
        if deleted_any:
            client.invalidate_all()
            _rerun()


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
        else:
            err = client.take_last_error()
            st.error((err or {}).get("detail")
                     or "Stats load failed — is the backend up?")
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
        else:
            err = client.take_last_error()
            st.error((err or {}).get("detail")
                     or "Graph load failed — is the backend up?")
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
    else:
        err = client.take_last_error()
        st.warning((err or {}).get("detail")
                   or f"Could not load lecture #{pick['id']} — try again.")