"""Ingest + process panels — the two things a student does to a lecture.

Ingest owns upload (form, duplicate detection, the non-blocking upload thread
hand-off). Process owns the three pipeline actions (extract concepts, rebuild
graph, cut clips) and disables itself while a job is already running.
"""

from pathlib import Path

import streamlit as st

from frontend import client, state
from frontend.panels import library, shell


def duplicate_lecture(course_id, filename):
    """Return the id of an existing lecture that looks like this upload."""
    if not filename:
        return None
    stem = Path(filename).stem.lower()
    for lec in (client.list_lectures() or []):
        if lec.get("course_id") != course_id:
            continue
        title = (lec.get("title") or "").lower()
        if title == stem or filename.lower() == (lec.get("title") or "").lower():
            return lec["id"]
    return None


def render_ingest_form(upload_course):
    """The upload form plus its duplicate guard and progress monitor.

    Returns True when the caller should keep rendering (always, today) so the
    function can grow follow-ups without changing the entrypoints.
    """
    with st.form("upload_form"):
        backend = st.selectbox(
            "Transcription backend",
            ["auto", "local", "groq"],
            help="auto: groq when GROQ_API_KEY + ffmpeg are available (≈10× "
                 "real-time live-measured), otherwise the bundled local Whisper.",
        )
        up = st.file_uploader("Lecture media (mp4/mp3/wav/m4a/mkv/mov/webm)")
        submit = st.form_submit_button("Upload + transcribe")

    dup = duplicate_lecture(upload_course, up.name if up else None)
    if up and dup:
        st.warning(f"Duplicate: lecture #{dup} already exists for course "
                   f"'{upload_course}' with this filename. Uploading will create "
                   "a second row.")
        dedupe_ok = st.checkbox("Upload anyway (I know it's a duplicate)",
                                key="dup_upload_ok")
    else:
        dedupe_ok = True

    if submit and up and dedupe_ok:
        if not client.valid_course_id(upload_course):
            st.error("Course ID must be 1-128 alphanumeric/hyphen/underscore chars.")
        else:
            data = {"course_id": upload_course, "title": Path(up.name).stem}
            if backend != "auto":
                data["whisper_backend"] = backend
            resp = client.post("/lectures", data=data)
            err = client.take_last_error()
            if resp:
                client.invalidate_all()
                started = shell.begin_upload(
                    upload_course, resp["id"], "Upload + transcribe", up.name,
                    up.getvalue(),
                    whisper_backend=backend if backend != "auto" else None,
                )
                st.success(
                    f"Uploading lecture #{resp['id']} — the transfer runs in the "
                    "background; progress card below."
                    if started else
                    "Upload already in progress — see the progress card below."
                )
            elif err:
                st.error(err.get("detail") or "Upload failed.")
    elif submit and up and not dedupe_ok:
        st.info("Duplicate upload not sent — tick 'Upload anyway' to proceed.")

    # upload/transcription progress sits directly under the upload controls
    shell.render_progress_cards(kinds=("upload", "transcribe", "attach"))


def render_process_controls(nav_course):
    """Extract concepts / rebuild graph / cut clips, disabled while busy."""
    st.subheader("Process a lecture")
    st.caption("Extract concepts → auto-rebuild the course graph → cut clips.")

    ready = library.ready_lectures(nav_course)
    if not ready:
        st.warning(f"No ready lecture in course '{nav_course}' — upload one above.")
        return

    chosen = st.selectbox("Lecture to process", ready,
                          format_func=library.lecture_label,
                          key="process_lecture")
    # One pipeline job at a time per lecture: a second click would queue
    # duplicate work behind the same semaphore slot.
    busy = shell.active_job(chosen["id"], kinds=("extract", "graph", "clips"))
    if busy:
        st.info("A job is already running for this lecture — progress is shown "
                "just below. Actions stay disabled until it finishes.")

    if st.button("Extract concepts + build graph", disabled=busy):
        resp = client.post(f"/lectures/{chosen['id']}/concepts")
        err = client.take_last_error()
        if resp:
            shell.start_job(nav_course, chosen["id"],
                            "Concept extraction + graph", kind="extract")
        elif err:
            st.error(err.get("detail") or "Extraction not queued.")

    if st.button("Rebuild graph only (after edits/reruns)", disabled=busy):
        resp = client.post(f"/courses/{nav_course}/graph",
                           params={"lecture_id": chosen["id"]})
        err = client.take_last_error()
        if resp:
            shell.start_job(nav_course, chosen["id"],
                            "Course-graph rebuild", kind="graph")
        elif err:
            st.error(err.get("detail") or "Graph build not queued.")

    if st.button("Cut concept clips", disabled=busy):
        resp = client.post(f"/lectures/{chosen['id']}/clips")
        err = client.take_last_error()
        if resp:
            shell.start_job(nav_course, chosen["id"], "Clip cutting",
                            kind="clips", after="clips_list")
        elif err:
            st.error(err.get("detail") or "Clip cutting not queued.")

    # Pipeline progress directly under the process buttons that queued it.
    shell.render_progress_cards(kinds=("extract", "graph", "clips"),
                                on_ready=library.clips_followup)
