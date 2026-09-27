"""App shell — sidebar, auth banner, usage row, snapshot strip, job monitor.

Everything that frames the page or reports background state lives here, so the
content panels (ingest / process / library / graph / quiz) never have to know
about session plumbing, the poll loop, or the upload thread registry.
"""

import threading
import time

import streamlit as st

from frontend import client, state

# ---------------------------------------------------------------- tunables

_MAX_POLL_FAILS = 5
_JOB_DEADLINE_S = 6 * 60 * 60
_JOB_DEADLINE_S_ALIAS = _JOB_DEADLINE_S

# Consecutive polls that may repeat the same non-advancing status before the job
# is called stalled. The backend's DB-derived fallback reports a lecture's raw
# status, so a row stuck in `uploaded` is reported identically forever; without a
# cutoff the page re-rendered every 0.5-1.5s until the 6h deadline. Heavy stages
# publish only coarse milestones around work that legitimately takes minutes, so
# they get a much larger allowance.
_MAX_STALLED_POLLS = 40
_SLOW_STAGES = {"building_graph", "extracting", "cutting_clips", "clips",
                "local_transcribing", "loading_model", "transcribing"}
_MAX_STALLED_POLLS_SLOW = 600      # ~15 min at the 1.5s long-stage backoff

# In-process upload registry keyed by lecture id — module-level so a background
# upload thread survives between script executions. Guarded because the daemon
# upload thread and the per-session script thread both touch it, and it is
# process-global, so two sessions share it.
_UPLOADS = {}
_UPLOADS_LOCK = threading.RLock()

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
    "cutting_clips": "Cutting concept clips with ffmpeg (re-encoded, several "
                     "minutes for many clips)…",
    "saving_clips": "Saving clip rows…",
}

_LONG_STAGES = {
    "loading_model", "local_transcribing", "transcribing", "extracting",
    "building_graph", "clips", "cutting_clips", "saving_clips", "downmixing",
    "chunking",
}


# ------------------------------------------------------------------ sidebar

def course_sidebar():
    """Course picker + readiness caption + course delete, in the sidebar."""
    st.subheader("Course")
    courses = _course_options()
    if not courses:
        st.caption("No courses yet.")
        st.session_state.nav_course = None
        return None

    if "nav_course" not in st.session_state or st.session_state.nav_course not in courses:
        st.session_state.nav_course = courses[0]

    nav = st.selectbox("Active course", courses, key="nav_course")

    summaries = client.course_summaries() or []
    row = next((c for c in summaries if c.get("course_id") == nav), None)
    if row:
        st.caption(f"{row.get('total_lectures', 0)} lectures · "
                   f"{row.get('ready_lectures', 0)} ready · "
                   f"{row.get('total_concepts', 0)} concepts · "
                   f"{row.get('node_count', 0)} graph nodes")
        data = client.course_snapshot(nav)
        if data:
            st.caption(_snapshot_line(data))

    if st.button("Refresh course list"):
        client.invalidate_all()
        _rerun()

    with st.expander("Delete this course"):
        st.caption("Removes every lecture, concept, graph row and clip for the "
                   "course, plus the uploaded media.")
        if st.button(f"Delete '{nav}' permanently", key="delete_course"):
            res = client.delete(f"/courses/{nav}")
            if res:
                st.success(res.get("message") or "Course deleted.")
                client.invalidate_all()
                st.session_state.pop("nav_course", None)
                _rerun()
            else:
                err = client.take_last_error()
                st.error((err or {}).get("detail") or "Delete failed.")
    return nav


def _course_options():
    courses = sorted({c["course_id"] for c in (client.course_summaries() or [])})
    if courses:
        return courses
    return sorted({l["course_id"] for l in (client.list_lectures() or [])
                   if l.get("course_id")})


def rerun():
    """``st.rerun`` tolerantly — AppTest and bare runtimes may not have it."""
    _rerun()


def _rerun():
    try:
        st.rerun()
    except Exception:  # noqa: BLE001 - AppTest / bare runtimes have no rerun
        pass


# -------------------------------------------------------------------- usage

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
    data = client.usage()
    if not data:
        return
    duration = _active_transcribe_duration()
    for line in _usage_summary(data.get("services", {}),
                               data.get("availability"), duration):
        st.caption(f"LectGap quota — {line}")


def _active_transcribe_duration():
    for j in (state.get("jobs", "items") or []):
        if j.get("kind") in ("upload", "transcribe"):
            return j.get("duration_s")
    return None


# --------------------------------------------------------------------- auth

def render_auth_banner():
    err = client.take_last_error()
    if err and err.get("kind") == "auth":
        st.error("Unauthorized — check LECGAP_API_KEY on the backend and in "
                 "frontend/.env.")


# ------------------------------------------------------------ upload thread

def _sleep(seconds):
    """Indirection over time.sleep for the poll back-off.

    The monitor is a deliberate stop/sleep/rerun loop, so under Streamlit's
    AppTest a seeded job would burn the whole 3s run budget re-rendering. Tests
    neutralise this one function; production keeps the real back-off.
    """
    time.sleep(seconds)


def begin_upload(course_id, lecture_id, title, filename, file_bytes,
                 whisper_backend=None):
    """Stream the media in a daemon thread so the script never blocks on it."""
    with _UPLOADS_LOCK:
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
    with _UPLOADS_LOCK:
        _UPLOADS[lecture_id] = {"thread": thread, "cancel": cancel, "done": done,
                                "ok": outcome, "title": title}
    thread.start()
    start_job(course_id, lecture_id, title, kind="upload")
    return True


def cancel_upload(lecture_id):
    with _UPLOADS_LOCK:
        entry = _UPLOADS.get(lecture_id)
        if entry and not entry["done"].is_set():
            entry["cancel"].set()
            return True
    return False


def _upload_status(lecture_id, kind):
    """``(state, ok, error)`` for an upload job; ``state`` is one of:

    * ``"done"``   - the transfer finished; read ``ok``/``error`` for the result.
    * ``"pending"``- a live registry entry whose thread has not finished.
    * ``"absent"`` - no registry entry at all: the thread is gone (it was never
      started, or a previous poll already consumed the result).

    The three states used to collapse: "pending" and "absent" both returned
    ``(False, False, None)``, so the monitor could not tell a transfer still in
    flight from one with no thread behind it and reported "Upload failed." on
    the first poll, making the Cancel button unreachable.
    """
    if kind != "upload":
        return None
    with _UPLOADS_LOCK:
        entry = _UPLOADS.get(lecture_id)
        if entry is None:
            return "absent", False, None
        if entry["done"].is_set():
            # read what we need before dropping it, so a concurrent reader can
            # never observe a half-removed entry
            ok, err = entry["ok"]["ok"], entry["ok"]["error"]
            _UPLOADS.pop(lecture_id, None)  # handled; keep memory tight
            return "done", ok, err
    return "pending", False, None


# ------------------------------------------------------------- job registry

def start_job(course_id, lecture_id, title, kind, after=None):
    """Remember a background job so the monitor renders its card next rerun.

    Jobs accumulate - starting a new one never drops an old card. Identical
    (lecture, kind) pairs are coalesced.
    """
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


def active_job(lecture_id, kinds=None):
    """True while a monitor card for this lecture is still live.

    Lets action buttons disable themselves instead of letting a second click
    queue duplicate work (Streamlit reruns the whole script per interaction, so
    a double-click fired the request twice).
    """
    for j in (state.get("jobs", "items") or []):
        if j.get("lecture_id") != lecture_id:
            continue
        if kinds is None or j.get("kind") in kinds:
            return True
    return False


def _job_guidance(stage, elapsed_s):
    hint = _STAGE_HINTS.get(stage, f"Currently: {stage or 'working'}.")
    mm, ss = divmod(int(elapsed_s or 0), 60)
    if mm:
        return f"{hint}  ({mm}m {ss:02d}s elapsed)"
    return f"{hint}  ({ss}s elapsed)"


def render_progress_cards(kinds=None, on_ready=None):
    """Live, self-refreshing progress card per monitored job.

    One poll per rerun with adaptive back-off. ``kinds`` restricts the call to a
    subset of job kinds and leaves the others untouched, so the dashboard can
    render the ingest monitor and the process monitor as two separate blocks -
    each directly under the controls that started those jobs.

    ``on_ready(job, lecture_id)`` is invoked for a job that lands on ``ready``,
    which is how a panel attaches its own follow-up (e.g. the clip list) without
    the monitor knowing anything about clips.
    """
    items = state.get("jobs", "items", []) or []
    if not items:
        return

    mine = [j for j in items if kinds is None or j.get("kind") in kinds]
    others = [j for j in items if kinds is not None and j.get("kind") not in kinds]
    if not mine:
        return

    keep, want_rerun, backoff = [], False, 1.5
    for job in mine:
        lecture_id = job.get("lecture_id")
        kind = job.get("kind")

        # --- non-blocking upload: handle the client-side upload thread first ---
        if kind == "upload":
            up_state, up_ok, up_err = _upload_status(lecture_id, kind)
            if up_state == "absent":
                st.error(up_err or "Upload failed.")
                client.invalidate_for_course(job.get("course_id"))
                continue
            if up_state == "done":
                if not up_ok:
                    st.error(up_err or "Upload failed.")
                    client.invalidate_for_course(job.get("course_id"))
                    continue
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
        pct = int(data.get("progress_pct", 0) or 0)

        if status == "ready":
            st.progress(100)
            st.success(data.get("detail") or f"{job.get('title')} — Done.")
            client.invalidate_for_course(job.get("course_id"))
            if on_ready is not None:
                on_ready(job, lecture_id)
            continue
        if status in ("error", "not_found"):
            st.error(data.get("detail") or f"Job ended with status '{status}'.")
            client.invalidate_for_course(job.get("course_id"))
            continue

        # Stall detection: a job reporting an identical stage+pct every poll is
        # not making progress.
        fingerprint = f"{status}|{stage}|{pct}"
        if job.get("fingerprint") == fingerprint:
            job["stalled_polls"] = int(job.get("stalled_polls", 0)) + 1
        else:
            job["fingerprint"] = fingerprint
            job["stalled_polls"] = 0
        budget = (_MAX_STALLED_POLLS_SLOW if stage in _SLOW_STAGES
                  else _MAX_STALLED_POLLS)

        if kind == "upload" and status == "uploaded":
            st.progress(0, text="Upload starting…")
            st.caption(job.get("title", "Upload"))
            if job["stalled_polls"] >= budget:
                st.warning("Upload is not starting — the backend never picked up "
                           "the media. Delete the row and re-upload it.")
                continue
            keep.append(job)
            want_rerun = True
            backoff = min(backoff, 0.5)
            continue

        st.progress(min(pct, 100), text=data.get("detail") or stage)
        st.caption(_job_guidance(stage, data.get("elapsed_s", 0)))

        if job["stalled_polls"] >= budget:
            st.warning(f"Stalled on '{stage}' with no progress for a while — the "
                       "job may have stopped. Reload the page to re-attach to it.")
            continue
        if time.monotonic() > float(job.get("deadline", 0)):
            st.warning("Timed out waiting — the job still runs in the "
                       "background; reload to re-attach.")
            continue
        keep.append(job)
        want_rerun = True
        backoff = min(backoff, 1.5 if stage in _LONG_STAGES else 0.5)

    state.set("jobs", items=keep + others)
    if want_rerun:
        _sleep(backoff)
        _rerun()


# ----------------------------------------------------------------- snapshot

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
    """Live course-readiness strip.

    The 5s snapshot drives both dashboards so a change made in one session
    surfaces in the other. Seeds monitor cards only for *transcribing* lectures
    (a stuck ``uploaded`` row is a hint, never a spinning card).
    """
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
        # The snapshot cannot tell a resumable row from an abandoned one, so it
        # must not claim they are all broken. Point at the panel that can.
        ids = ", ".join(f"#{f['lecture_id']}" for f in uploading)
        st.info(f"{len(uploading)} lecture(s) are not finished yet: {ids}. "
                "See 'Ready to process' / 'Incomplete uploads' below — each one "
                "either needs processing started, or needs deleting.")


def _seed_monitor_from_snapshot(course_id, transcribing):
    """Attach monitor cards for backend jobs a fresh tab wasn't present for."""
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
