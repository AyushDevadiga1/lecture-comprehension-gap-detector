"""LecGap — Student dashboard.

Run with the backend already up:
    streamlit run frontend/student_app.py

This file is deliberately thin wiring only: it decides *order* and nothing
else. Every behaviour lives in ``frontend.panels`` (one module per concern) and
``frontend.client`` is the only HTTP boundary. That split is what makes each
panel independently testable, and what lets the layout be fixed in one place
instead of once per panel.
"""

import streamlit as st

from frontend import client, components
from frontend.panels import graph, ingest, library, quiz, shell

st.set_page_config(page_title="LecGap · Student", layout="wide")
st.title("LecGap")
st.caption("Lecture Comprehension Gap Detector — Student dashboard")

with st.sidebar:
    nav_course = shell.course_sidebar()

shell.render_auth_banner()
shell.render_usage_row()
shell.render_course_snapshot(nav_course)

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
    ingest.render_ingest_form(upload_course)
else:
    st.info("Upload media above to create the first course.")

st.divider()
if nav_course is None:
    st.warning("No course available to process yet — upload one above.")
    st.stop()

ingest.render_process_controls(nav_course)

st.divider()
st.subheader("Concept clips")
library.clip_watch_picker(nav_course)

st.divider()
library.render_stalled_rows(nav_course)

st.divider()
st.subheader("Course graph")
graph.render_course_graph(nav_course)

st.divider()
components.render_lecture_rows(nav_course)

st.divider()
quiz.render_quiz(nav_course)
