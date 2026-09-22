"""Background jobs — the seamed entrypoint surface routes schedule.

One module per job keeps each pipeline responsibility inspectable and its
failure path local:

    transcribe.py       — process_lecture()            (Stage 1)
    extract.py          — extract_concepts_worker()    (Stage 2 + chained graph)
    clips.py            — cut_clips_worker()           (Stage 5)
    graph.py            — build_course_graph_worker()  (Stage 4)
    progress.py         — update_lecture_progress() / get_lecture_progress()
    purge.py            — purge_course()               (course teardown)
    common.py           — shared classifier singleton, semaphore, error sanitizer

This __init__ re-exports only what routes call; internals live in the
per-job modules.
"""

from backend.api.jobs.clips import cut_clips_worker
from backend.api.jobs.extract import extract_concepts_worker
from backend.api.jobs.graph import build_course_graph_worker
from backend.api.jobs.progress import get_lecture_progress, update_lecture_progress
from backend.api.jobs.purge import purge_course
from backend.api.jobs.transcribe import process_lecture

__all__ = [
    "build_course_graph_worker",
    "cut_clips_worker",
    "extract_concepts_worker",
    "get_lecture_progress",
    "process_lecture",
    "purge_course",
    "update_lecture_progress",
]