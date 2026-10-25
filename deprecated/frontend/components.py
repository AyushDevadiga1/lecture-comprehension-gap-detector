"""Component facade — the stable public surface of the Streamlit frontend.

The implementation lives in :mod:`frontend.panels`, one module per concern:

    shell.py    sidebar, auth banner, quota row, snapshot strip, job monitor,
                the upload thread registry
    ingest.py   the upload form and the process-a-lecture controls
    library.py  concept clips (players) and lecture-row management
    graph.py    the course DAG + the faculty DAG
    quiz.py     generate / answer / submit / review

This module re-exports those names so existing imports
(``from frontend import components``) and the test-suite keep working, and so
there is exactly one place to look for "what can a dashboard call".

Keeping the facade means the split is a refactor, not an API change: the
Streamlit entrypoints and every existing test continue to import
``components.render_*`` unchanged.
"""

from frontend.panels.graph import render_course_graph, render_faculty_dag
from frontend.panels.ingest import (
    duplicate_lecture,
    render_ingest_form,
    render_process_controls,
)
from frontend.panels.library import (
    clip_rows,
    clip_watch_picker,
    clips_followup,
    lecture_label,
    ready_lectures,
    render_clips,
    render_lecture_rows,
    render_stalled_rows,
    stalled_rows,
)
from frontend.panels.quiz import render_quiz
from frontend.panels.shell import (
    _JOB_DEADLINE_S,
    _MAX_POLL_FAILS,
    _MAX_STALLED_POLLS,
    _MAX_STALLED_POLLS_SLOW,
    _SLOW_STAGES,
    _UPLOADS,
    _UPLOADS_LOCK,
    _job_guidance,
    _snapshot_line,
    _upload_status,
    _usage_summary,
    active_job,
    begin_upload,
    cancel_upload,
    course_sidebar,
    drain_ready,
    render_auth_banner,
    render_course_snapshot,
    render_progress_cards,
    render_usage_row,
    rerun,
    start_job,
)

__all__ = [
    # shell
    "course_sidebar", "render_auth_banner", "render_usage_row",
    "render_course_snapshot", "render_progress_cards", "drain_ready", "rerun",
    "start_job", "active_job", "begin_upload", "cancel_upload",
    "_snapshot_line", "_usage_summary", "_upload_status",
    "_UPLOADS", "_UPLOADS_LOCK", "_MAX_POLL_FAILS", "_MAX_STALLED_POLLS",
    "_MAX_STALLED_POLLS_SLOW", "_SLOW_STAGES", "_JOB_DEADLINE_S", "_job_guidance",
    # ingest
    "render_ingest_form", "render_process_controls", "duplicate_lecture",
    # library
    "render_clips", "clip_watch_picker", "clip_rows", "clips_followup",
    "render_lecture_rows", "render_stalled_rows", "stalled_rows",
    "lecture_label", "ready_lectures",
    # graph
    "render_course_graph", "render_faculty_dag",
    # quiz
    "render_quiz",
    # faculty
    "render_faculty_stats", "render_faculty_timeline",
]


def __getattr__(name):
    """Lazily expose the faculty panels without importing Streamlit eagerly.

    The faculty view is only used by ``faculty_app.py``; resolving it on
    demand keeps ``import components`` cheap and avoids a circular import
    between the facade and the faculty module.
    """
    if name in ("render_faculty_stats", "render_faculty_timeline"):
        from frontend.panels import faculty
        return getattr(faculty, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
