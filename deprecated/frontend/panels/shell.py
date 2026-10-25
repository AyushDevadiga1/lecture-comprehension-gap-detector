"""App shell — sidebar, auth banner, usage row, snapshot strip, job monitor.

Everything that frames the page or reports background state lives here, so the
content panels (ingest / process / library / graph / quiz) never have to know
about session plumbing, the job feed, or the upload thread registry.
"""

import threading
import time

import streamlit as st

from frontend import client, jobfeed, state

# ---------------------------------------------------------------- tunables

_MAX_POLL_FAILS = 5

# Backstop only. A job settles on a terminal status in the durable registry, so
# this should never fire; it exists so a job whose feed has gone quiet is
# dropped with an explanation instead of rendering forever.
_JOB_DEADLINE_S = 6 * 60 * 60

# How often the progress-card fragment re-executes. Short enough to feel live,
# long enough not to hammer the backend. The card does no fetching of its own -
# it reads the SSE feed's in-memory snapshot.
_REFRESH = "1s"

# Consecutive ticks that may repeat the same non-advancing status before the job
# is called stalled. A tick is one fragment re-execution (_REFRESH), not a page
# rerun: the backend's DB-derived fallback reports a lecture's raw status, so a
# row stuck in `uploaded` is reported identically forever, and without a cutoff
# the card would render for the full 6h backstop. Heavy stages publish only
# coarse milestones around work that legitimately takes minutes, so they get a
# much larger allowance - 600 ticks is ~10 minutes at _REFRESH.
_MAX_STALLED_POLLS = 40
_SLOW_STAGES = {"building_graph", "extracting", "cutting_clips", "clips",
                "local_transcribing", "loading_model", "transcribing"}
_MAX_STALLED_POLLS_SLOW = 600

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

def begin_upload(course_id, lecture_id, title, filename, file_bytes,
                 whisper_backend=None):
    """Stream the media in a daemon thread so the script never blocks on it."""
    with _UPLOADS_LOCK:
        entry = _UPLOADS.get(lecture_id)
        if entry and not entry["done"].is_set():
            return False  # already uploading this lecture

    cancel = threading.Event()
    done = threading.Event()
    outcome = {"ok": False, "error": None, "job_id": None}

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
            else:
                outcome["ok"] = True
                # the PUT enqueued the durable transcription job, so the card
                # can follow the real thing from here on instead of guessing
                outcome["job_id"] = resp.get("job_id")
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
    """``(state, ok, error, job_id)`` for an upload job; ``state`` is one of:

    * ``"done"``   - the transfer finished; read ``ok``/``error`` for the result
      and ``job_id`` for the transcription job the PUT enqueued.
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
            return "absent", False, None, None
        if entry["done"].is_set():
            # read what we need before dropping it, so a concurrent reader can
            # never observe a half-removed entry
            ok = entry["ok"]["ok"]
            err = entry["ok"]["error"]
            job_id = entry["ok"].get("job_id")
            _UPLOADS.pop(lecture_id, None)  # handled; keep memory tight
            return "done", ok, err, job_id
    return "pending", False, None, None


# ------------------------------------------------------------- job registry

def start_job(course_id, lecture_id, title, kind, after=None, job_id=None):
    """Remember a background job so the monitor renders its card next rerun.

    Jobs accumulate - starting a new one never drops an old card. Identical
    (lecture, kind) pairs are coalesced.

    ``job_id`` is the durable row the backend created for this work (Engine 2 /
    C3). When present the monitor reads that row from the job feed instead of
    polling the legacy per-lecture endpoint.
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
        "job_id": job_id,
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


def render_progress_cards(kinds=None, feed=None):
    """Live progress cards, rendered inside a self-refreshing fragment.

    C4: this used to call ``st.rerun()`` in a sleep/poll loop, which re-executed
    the whole script and therefore rebuilt every element on the page - restarting
    each ``<video>`` player and making long lists unusable while a job ran.

    Now the cards live in a ``st.fragment(run_every=...)``, so only this block
    re-executes; the rest of the page stays mounted. Progress itself arrives
    over the SSE job feed (see :mod:`frontend.jobfeed`), so rendering does not
    have to fetch anything.

    ``kinds`` restricts the call to a subset of job kinds and leaves the others
    untouched, so the dashboard can render the ingest monitor and the process
    monitor as two separate blocks - each directly under the controls that
    started those jobs.

    Call :func:`drain_ready` once per full page pass to render whatever finished
    (and any panel follow-up); that must stay outside the fragment, or the
    follow-up would be rebuilt every second.
    """
    def _block():
        # Re-read the job list every tick: the fragment may hold a stale list
        # while the rest of the page is untouched. This block's verdict is
        # written back, and jobs belonging to the *other* monitor are carried
        # over untouched.
        current = state.get("jobs", "items", []) or []
        mine = [j for j in current if _owns(j, kinds)]
        if not mine:
            return
        keep = render_job_cards(mine, feed=feed)
        others = [j for j in (state.get("jobs", "items", []) or [])
                  if not _owns(j, kinds)]
        state.set("jobs", items=list(keep) + others)

    _auto_refreshing(_block)()


def _owns(job, kinds):
    return kinds is None or job.get("kind") in kinds


def _auto_refreshing(fn):
    """Schedule ``fn`` to re-execute on its own, when Streamlit supports it.

    ``st.fragment(run_every=...)`` re-executes *only* the wrapped block, which is
    the whole point of C4: the clip players, graph and quiz elsewhere on the
    page stay mounted instead of being rebuilt on every poll. Where there is no
    fragment scheduler (AppTest, Streamlit older than 1.37) the block simply
    renders once per rerun - the legacy behaviour, which still works.

    Only the two "not supported" shapes fall back silently. Any other exception
    is re-raised: a monitor that quietly stops refreshing is the exact failure
    C4 was written to remove, so it must not degrade into "looks fine, frozen".
    """
    try:
        return st.fragment(fn, run_every=_REFRESH)
    except (AttributeError, TypeError):  # no fragment support -> plain render
        return fn


def render_job_cards(items, feed=None):
    """Render one card per job; return the jobs that are still live.

    Split out from :func:`render_progress_cards` so it can be driven directly by
    tests, which cannot rely on Streamlit's fragment scheduler running. It never
    fetches anything for a job the feed knows about, and never reruns the page -
    a completion is recorded in session state and rendered by the dashboard
    itself, outside the fragment (see :func:`drain_ready`).
    """
    keep = []
    if not items:
        return keep
    if feed is None:
        feed = _feed_for(items)

    for job in items:
        if job.get("kind") == "upload":
            keep.extend(_upload_step(job))
            continue
        remote = feed.job(job.get("job_id")) if feed is not None else None
        if remote is None:
            reading = _legacy_reading(job)
            if reading is None:
                keep.extend(_unreachable(job))
                continue
            status, stage, pct, detail, terminal = reading
            elapsed = 0
        else:
            status = remote.get("status", "")
            stage = remote.get("stage") or ""
            pct = int(remote.get("progress_pct", 0) or 0)
            detail = remote.get("detail")
            terminal = bool(remote.get("terminal"))
            elapsed = remote.get("duration_s") or 0

        job["fingerprint"] = f"{status}|{stage}|{pct}"
        if job.get("_fp") == job["fingerprint"]:
            job["stalled_polls"] = int(job.get("stalled_polls", 0)) + 1
        else:
            job["_fp"] = job["fingerprint"]
            job["stalled_polls"] = 0

        if status == "ready":
            st.progress(100)
            _record_ready(job, detail)
            continue
        if status in ("error", "not_found", "cancelled", "orphaned"):
            label = {"orphaned": "stopped by a server restart",
                     "cancelled": "cancelled"}.get(status, status)
            st.error(detail or f"Job ended with status '{label}'.")
            client.invalidate_for_course(job.get("course_id"))
            continue

        st.progress(min(pct, 100), text=detail or stage)
        st.caption(_job_guidance(stage, elapsed))

        budget = (_MAX_STALLED_POLLS_SLOW if stage in _SLOW_STAGES
                  else _MAX_STALLED_POLLS)
        if job["stalled_polls"] >= budget:
            st.warning(f"Stalled on '{stage}' with no progress for a while — "
                       "the job may have stopped. Reload to re-attach.")
            continue
        if _over_deadline(job):
            continue
        if not terminal:
            keep.append(job)
    return keep


def _over_deadline(job):
    """Backstop: drop a job that has been watched for an absurdly long time."""
    if time.monotonic() <= float(job.get("deadline") or 0):
        return False
    st.warning("Timed out waiting — the job still runs in the background; "
               "reload to re-attach.")
    return True


def _feed_for(items, feed=None):
    """The feed to read, or None. Only started once a job has a durable row.

    A job queued before the backend returned its id (the client-side upload
    transfer, a pre-C3 backend) has nothing to look up, so no connection is
    opened for it - the legacy per-lecture endpoint answers those.
    """
    if feed is not None:
        return feed
    if not any(j.get("job_id") is not None for j in items):
        return None
    try:
        return jobfeed.job_feed()
    except Exception:  # noqa: BLE001 - the UI must not break on the feed
        return None


def _legacy_reading(job):
    """``(status, stage, pct, detail, terminal)`` from the per-lecture endpoint.

    Returns None when the endpoint is unreachable; the caller counts the miss
    and gives up after ``_MAX_POLL_FAILS``. A job that has a durable id but no
    feed row yet lands here too, which is exactly the window between "the POST
    returned" and "the stream connected" - it must not look like a dead worker.
    """
    data = client.get(f"/lectures/{job.get('lecture_id')}/progress")
    if not data:
        return None
    status = data.get("status", "")
    return (status, data.get("stage", "working"),
            int(data.get("progress_pct", 0) or 0), data.get("detail"),
            status in ("ready", "error", "not_found", "cancelled", "orphaned"))


def _unreachable(job):
    """Keep or drop a job whose progress endpoint cannot be read."""
    job["fail_count"] = int(job.get("fail_count", 0)) + 1
    if job["fail_count"] < _MAX_POLL_FAILS:
        return [job]
    st.warning(f"Job '{job.get('title', '')}' is queued but unreachable — "
               "the worker may have stopped. Refresh to re-attach.")
    return []


def _upload_step(job):
    """One tick of a client-side upload card; returns the jobs to keep.

    The transfer runs in *this* process, so the card has no durable row to read
    and its percentage comes from the per-lecture progress the PUT publishes.
    The moment the transfer lands, ``PUT /lectures/{id}/media`` returns the
    transcription job it enqueued, and the card becomes that job's card - which
    is why the returned list carries the same dict, mutated.
    """
    lecture_id = job.get("lecture_id")
    up_state, ok, err, job_id = _upload_status(lecture_id, "upload")
    if up_state == "absent":
        st.error(err or "Upload failed.")
        client.invalidate_for_course(job.get("course_id"))
        return []
    if up_state == "done":
        if not ok:
            st.error(err or "Upload failed.")
            client.invalidate_for_course(job.get("course_id"))
            return []
        job["kind"] = "transcribe"
        job["job_id"] = job_id
        job["_fp"] = None
        job["stalled_polls"] = 0
        return [job]

    if st.button("Cancel upload", key=f"cancel_up_{lecture_id}"):
        cancel_upload(lecture_id)

    data = client.get(f"/lectures/{lecture_id}/progress") or {}
    if data.get("status") != "uploaded":
        # the backend already moved on (or knows nothing yet): the next tick
        # renders the transcription card this is about to become
        return [] if _over_deadline(job) else [job]

    st.progress(int(data.get("progress_pct", 0) or 0),
                text=data.get("detail") or "Uploading…")
    st.caption(job.get("title", "Upload"))
    job["stalled_polls"] = int(job.get("stalled_polls", 0)) + 1
    if job["stalled_polls"] >= _MAX_STALLED_POLLS:
        st.warning("Upload is not starting — the backend never picked up the "
                   "media. Delete the row and re-upload it.")
        return []
    return [] if _over_deadline(job) else [job]


def _record_ready(job, detail):
    """Finish a job: invalidate its course and remember what to announce.

    The announcement is *not* rendered here. A fragment re-executes every second,
    so a success message rendered inside it would flash and vanish. It is
    recorded in session state and rendered by the dashboard on the next full
    pass (:func:`drain_ready`), which is also where a panel's ``on_ready``
    follow-up belongs.
    """
    client.invalidate_for_course(job.get("course_id"))
    pending = state.get("jobs", "completed", []) or []
    pending.append({"lecture_id": job.get("lecture_id"),
                    "course_id": job.get("course_id"),
                    "title": job.get("title"),
                    "after": job.get("after"),
                    "detail": detail or f"{job.get('title')} — Done."})
    state.set("jobs", completed=pending)
    return pending


def drain_ready(on_ready=None):
    """Render (once) the jobs that finished since the last pass.

    Called by a dashboard *outside* the fragment, so the "Done" line and the
    panel's follow-up land in the page body and stay put until the reader does
    something else.
    """
    pending = state.get("jobs", "completed", []) or []
    if not pending:
        return
    state.set("jobs", completed=[])
    for record in pending:
        st.success(record.get("detail") or "Done.")
        if on_ready is not None and record.get("after"):
            on_ready({"after": record["after"]}, record.get("lecture_id"))


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
