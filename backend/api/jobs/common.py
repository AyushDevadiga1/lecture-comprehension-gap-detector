"""Shared job plumbing — the one place a job failure turns into a client message.

Hosts the process-wide classifier singleton (H4), the pipeline concurrency
throttle, and the M2 error sanitizer used by every long-running job. Route and
DB code should never read the classifier seeds or throttle directly; go through
these.
"""

import logging
from pathlib import Path
import threading

from backend.config import MAX_PIPELINE_JOBS

REPO_ROOT = Path(__file__).resolve().parents[3]

_LOGGER = logging.getLogger("lecgap.jobs")

# One long-lived classifier per process (H4): the MiniLM encoder weights and
# the LectureBank-fitted logistic head construct/fit ONCE and are reused by
# every course-graph rebuild. Previously each rebuild built a fresh
# PrerequisiteClassifier and re-fitted the head on ~42k rows, and re-loaded
# the encoder per stage.
_shared_clf_guard = threading.Lock()
_shared_clf = None

# Concurrency throttle: limits the number of simultaneously executing heavy
# pipeline jobs (transcription, concept extraction, clip cutting, graph build).
# Prevents OOM / CPU exhaustion when many uploads arrive in quick succession.
# LECGAP_MAX_PIPELINE_JOBS (>= 1, default 3) configures this in backend/config.py.
PIPELINE_SEMAPHORE = threading.BoundedSemaphore(MAX_PIPELINE_JOBS)


def get_shared_classifier():
    """Lazily construct (once per process) the shared prerequisite classifier."""
    global _shared_clf
    if _shared_clf is None:
        from backend.pipeline.classify_prerequisites import PrerequisiteClassifier

        with _shared_clf_guard:
            if _shared_clf is None:
                try:
                    _shared_clf = PrerequisiteClassifier()
                except Exception as exc:  # noqa: BLE001 — HF model load is network-dependent
                    raise RuntimeError(
                        f"Classifier model load failed: {type(exc).__name__}: {exc}"
                    ) from exc
    return _shared_clf


def client_error_message(exc: Exception, context: str = "Pipeline stage") -> str:
    """Sanitize a stage failure for the client (M2).

    Full exception detail and traceback are logged server-side; what lands in
    `lecture.error` (and is returned by GET /lectures[/{id}] / /progress) is a
    generic message — never ffmpeg stderr, temp paths, or Groq internals.
    """
    _LOGGER.exception("%s failed: %s", context, exc)
    return f"{context} failed — see server logs for details."