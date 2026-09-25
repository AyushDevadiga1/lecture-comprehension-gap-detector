"""LecGap — Faculty dashboard.

Run with the backend already up:
    streamlit run frontend/faculty_app.py

Faculty analytics (stats, DAG, timeline) plus the shared live job monitor, so
lecturers can see what the backend is doing at a glance regardless of who
started it. Loaded panels are persisted in Tier-2 session state — background-job
reruns never wipe them.
"""

import streamlit as st

from frontend import client, components

st.set_page_config(page_title="LecGap · Faculty", layout="wide")
st.title("LecGap")
st.caption("Lecture Comprehension Gap Detector — Faculty dashboard")

with st.sidebar:
    st.subheader("Course")
    nav_course = components.course_sidebar()

components.render_auth_banner()
components.render_usage_row()
components.render_progress_cards()
components.render_course_snapshot(nav_course)

if nav_course is None:
    st.info("No courses yet — upload a lecture from the Student dashboard.")
    st.stop()

components.render_faculty_stats(nav_course)
st.divider()
components.render_faculty_dag(nav_course)
st.divider()
components.render_faculty_timeline(nav_course)