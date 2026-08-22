"""
Streamlit entrypoint — student + faculty views, talking to the FastAPI
backend over HTTP only (never importing backend/pipeline/* directly —
see plan/ARCHITECTURE.md, "Decoupled architecture").

Run locally with:
    streamlit run frontend/app.py
(with the backend already running: uvicorn backend.main:app --reload)
"""

import streamlit as st

st.set_page_config(page_title="LecGap", layout="wide")

st.title("LecGap")
st.caption("Lecture Comprehension Gap Detector — Phase 0 scaffold. Nothing wired up yet.")

tab_student, tab_faculty = st.tabs(["Student", "Faculty"])

with tab_student:
    st.info("TODO (Phase 6): lecture upload, quiz, and dependency-ordered clip playback.")

with tab_faculty:
    st.info("TODO (Phase 8): confusion heatmap + taught-vs-learned divergence view.")
