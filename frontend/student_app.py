"""LecGap — Student dashboard.

Run with the backend already up:
    streamlit run frontend/student_app.py

Only talks to the backend through ``frontend.client`` (per
``plan/FRONTEND_API_CONTRACT.md``). UI logic lives in ``frontend.components``;
this file is thin wiring so the two dashboards stay independent and testable.
"""

import streamlit as st
from pathlib import Path

from frontend import client, components

st.set_page_config(page_title="LecGap · Student", layout="wide")
st.title("LecGap")
st.caption("Lecture Comprehension Gap Detector — Student dashboard")

with st.sidebar:
    st.subheader("Course")
    nav_course = components.course_sidebar()

components.render_auth_banner()
components.render_usage_row()
components.render_progress_cards()
components.render_course_snapshot(nav_course)

# ------------------------------------------------------------ ingest + process

upload_course = nav_course
if upload_course is None:
    st.warning("No course exists yet. Upload below to create the first course.")
    typed = st.text_input("Course ID (creates the course)", max_chars=128)
    upload_course = client.normalize_course_id(typed)
    if typed and not client.valid_course_id(upload_course):
        st.error("Course ID must be 1-128 alphanumeric/hyphen/underscore chars.")
        upload_course = None
    elif typed and upload_course != typed:
        st.caption(f"Will use canonical key `{upload_course}` (consistent everywhere).")

st.subheader("Ingest a lecture")
if upload_course:
    with st.form("upload_form"):
        backend = st.selectbox(
            "Transcription backend",
            ["auto", "local", "groq"],
            help="auto: groq when GROQ_API_KEY + ffmpeg are available (≈10× "
                 "real-time live-measured), otherwise the bundled local Whisper.",
        )
        up = st.file_uploader("Lecture media (mp4/mp3/wav/m4a/mkv/mov/webm)")
        submit = st.form_submit_button("Upload + transcribe")

    dup = components.duplicate_lecture(upload_course, up.name if up else None)
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
                started = components.begin_upload(
                    upload_course, resp["id"], "Upload + transcribe", up.name,
                    up.getvalue(),
                    whisper_backend=backend if backend != "auto" else None,
                )
                st.success(
                    f"Uploading lecture #{resp['id']} — the transfer runs in the "
                    f"background; progress card below."
                    if started else
                    "Upload already in progress — see the progress card below."
                )
            elif err:
                st.error(err.get("detail") or "Upload failed.")
    elif submit and up and not dedupe_ok:
        st.info("Duplicate upload not sent — tick 'Upload anyway' to proceed.")
else:
    st.info("Upload media above to create the first course.")

st.divider()
st.subheader("Process a lecture")
st.caption("Extract concepts → auto-rebuild the course graph → cut clips.")

if nav_course is None:
    st.warning("No course available to process yet — upload one above.")
    st.stop()

ready = components.ready_lectures(nav_course)
if not ready:
    st.warning(f"No ready lecture in course '{nav_course}' — upload one above.")
else:
    chosen = st.selectbox("Lecture to process", ready,
                          format_func=components.lecture_label,
                          key="process_lecture")
    if st.button("Extract concepts + build graph"):
        resp = client.post(f"/lectures/{chosen['id']}/concepts")
        err = client.take_last_error()
        if resp:
            components.start_job(nav_course, chosen["id"],
                                 "Concept extraction + graph", kind="extract")
        elif err:
            st.error(err.get("detail") or "Extraction not queued.")
    if st.button("Rebuild graph only (after edits/reruns)"):
        resp = client.post(f"/courses/{nav_course}/graph",
                           params={"lecture_id": chosen["id"]})
        err = client.take_last_error()
        if resp:
            components.start_job(nav_course, chosen["id"],
                                 "Course-graph rebuild", kind="graph")
        elif err:
            st.error(err.get("detail") or "Graph build not queued.")
    if st.button("Cut concept clips"):
        resp = client.post(f"/lectures/{chosen['id']}/clips")
        err = client.take_last_error()
        if resp:
            components.start_job(nav_course, chosen["id"], "Clip cutting",
                                 kind="clips", after="clips_list")
        elif err:
            st.error(err.get("detail") or "Clip cutting not queued.")

st.divider()
components.render_quiz(nav_course)