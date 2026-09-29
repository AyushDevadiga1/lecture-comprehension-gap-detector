"""Live per-lecture job progress.

Two stores, written together, during the C3 migration:

* the original process-memory dict, keyed by ``lecture_id``, which the shipped
  Streamlit UI still reads;
* the persisted ``jobs`` table, keyed by ``job_id`` (Engine 2 / C2), which
  survives a restart, is visible to every session, and is what the SSE stream
  serves.

``job_id`` is optional on every function here, so a caller with no job row —
and every existing test — behaves exactly as before. Passing it makes the
progress durable and cross-session; omitting it keeps the legacy path.

Entries in the in-memory store are pruned on a job's final state (ready/error)
so long-lived processes don't leak, and gets fall back to a DB-derived snapshot
once a job has ended.
"""

from contextlib import contextmanager
from datetime import datetime
import logging
import threading
import time

from backend.api import job_registry as registry
from backend.api.jobs.common import client_error_message
from backend.models.db import Lecture, SessionLocal

_LOGGER = logging.getLogger("lecgap.jobs.progress")

_progress_lock = threading.Lock()
_lecture_progress: dict = {}

# Ambient job id for the duration of one worker run.
#
# Each FastAPI BackgroundTask executes on its own thread, so a thread-local is
# exactly the right scope: wrapping a worker's body in ``job_scope(job_id)``
# makes every progress publish inside it dual-write, with no change to the ~20
# individual ``update_lecture_progress`` call sites and no risk of one of them
# being missed.
_scope = threading.local()


@contextmanager
def job_scope(job_id: int):
    """Bind ``job_id`` for the enclosing worker run.

    Also the crash net. A worker that raises used to leave its job row
    ``running`` with a frozen heartbeat *forever* — nothing called ``fail()`` —
    and that is what the 2026-09-29 "every button is dead" report actually was.
    See :func:`_settle_crash`.
    """
    previous = getattr(_scope, "job_id", None)
    _scope.job_id = job_id
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — re-raised; this only settles state
        _settle_crash(job_id, exc)
        raise
    finally:
        _scope.job_id = previous


def _settle_crash(job_id: int, exc: BaseException) -> None:
    """Turn an unhandled worker crash into a settled, honest ``error`` row.

    Without this, a worker that raised mid-persistence left three lies on the
    books at once: the job stayed ``running`` with a heartbeat frozen at the
    crash instant; ``useBusyLectureIds`` therefore kept the lecture busy and
    disabled its buttons for the whole six-hour ``JOB_DEADLINE_S`` backstop;
    and because a dead worker stops refreshing ``heartbeat_at``, the
    change-gated SSE snapshot stopped changing, so the UI never even learned
    the job had died. ``GET /jobs?active_only=true`` kept listing it.

    ``job_scope`` is the single choke point every worker passes through (which
    is why the ~20 ``update_lecture_progress`` call sites need no change), so
    this is the one place that has to be right.

    Best-effort by design: it runs while an exception is propagating and must
    never raise a second one.
    """
    if job_id is None:
        return
    try:
        row = registry.get_job(job_id) or {}
        msg = client_error_message(exc, f"{row.get('kind') or 'Job'} job")
        fail(row.get("lecture_id"), job_id, msg)
        lecture_id = row.get("lecture_id")
        if lecture_id is None:
            return
        with SessionLocal() as db:
            lecture = db.get(Lecture, lecture_id)
            # Never regress a lecture that already reached `ready`.
            if lecture is None or lecture.status == "ready":
                return
            lecture.status = "error"
            lecture.error = msg
            db.commit()
    except Exception:  # noqa: BLE001 — settling must not mask the real failure
        _LOGGER.exception("failed to settle crashed job %s", job_id)


def _active_job_id():
    return getattr(_scope, "job_id", None)


_STAGE_TO_STATUS = {
    "transcribing": "transcribing",
    "local_transcribing": "transcribing",
    "initializing": "transcribing",
    "probing": "transcribing",
    "downmixing": "transcribing",
    "loading_model": "transcribing",
    "chunking": "transcribing",
    "finalizing": "transcribing",
    "saving_segments": "transcribing",
    "extracting": "extracting",
    "building_graph": "building_graph",
    "cutting_clips": "clips",
    "clips": "clips",
    "saving_clips": "clips",
    "uploading": "uploading",
    "ready": "ready",
    "error": "error",
}


def _status_for(stage: str) -> str:
    """Derive the pipeline status word from the stage.

    The parameter used to default to the literal "transcribing", so a caller
    that omitted it stored status="transcribing" next to stage="extracting" -
    two fields disagreeing about the same run. Deriving keeps them consistent
    and makes the frontend's `status == "uploaded"` check reliable.
    """
    return _STAGE_TO_STATUS.get(stage, "transcribing")


def update_lecture_progress(
    lecture_id: int, stage: str, pct: int, detail: str, status: str = None,
    duration_s: float = None,
    job_id: int = None,
) -> None:
    """Publish progress for a running job.

    Writes the legacy in-memory entry always; writes the durable ``jobs`` row
    when a ``job_id`` is supplied or bound by :func:`job_scope`. ``status``
    defaults to the word implied by ``stage``.
    """
    status = status or _status_for(stage)
    with _progress_lock:
        entry = _lecture_progress.get(lecture_id)
        if entry is None:
            entry = _lecture_progress[lecture_id] = {"start_time": time.time()}
        entry["stage"] = stage
        entry["pct"] = int(max(0, min(pct, 100)))
        entry["detail"] = detail
        entry["status"] = status
        if duration_s is not None:
            entry["duration_s"] = float(duration_s)
        entry["updated_at"] = time.time()
    target = job_id if job_id is not None else _active_job_id()
    if target is not None:
        registry.update_job(target, stage=stage, progress_pct=pct, detail=detail,
                            status=_job_status_for(status))


def _job_status_for(status: str) -> str:
    """Map a pipeline status word onto the job state machine.

    The pipeline uses stage-flavoured words ("extracting", "building_graph")
    for work still in flight; the registry only cares queued/running/terminal.
    """
    if status in ("ready", "error", "cancelled", "orphaned"):
        return status
    if status in ("transcribing", "extracting", "building_graph", "clips",
                  "uploading"):
        return "running"
    return "running"


def _finish(lecture_id: int, job_id: int = None) -> None:
    """Drop the in-memory entry once a job settles (ready/error)."""
    with _progress_lock:
        _lecture_progress.pop(lecture_id, None)
    target = job_id if job_id is not None else _active_job_id()
    if target is not None:
        # A worker that reached _finish without an explicit terminal publish
        # still has to leave the durable row settled, or it would read as
        # running until the next restart orphaned it.
        current = registry.get_job(target)
        if current and not current.get("terminal"):
            registry.finish_job(target, status="ready")


def fail(lecture_id: int, job_id: int = None, error: str = None) -> None:
    """Settle both stores on failure."""
    with _progress_lock:
        _lecture_progress.pop(lecture_id, None)
    target = job_id if job_id is not None else _active_job_id()
    if target is not None:
        registry.fail_job(target, error or "job failed")


def get_lecture_progress(lecture_id: int) -> dict:
    """Snapshot of live progress, or a DB-derived fallback once the job ended."""
    with _progress_lock:
        prog = _lecture_progress.get(lecture_id)
        if prog is not None:
            elapsed = time.time() - prog["start_time"]
            return {
                "lecture_id": lecture_id,
                "status": prog.get("status", "transcribing"),
                "stage": prog.get("stage", "working"),
                "progress_pct": prog.get("pct", 0),
                "detail": prog.get("detail", "Processing..."),
                "elapsed_s": round(elapsed, 1),
                "duration_s": prog.get("duration_s"),
                "updated_at": datetime.fromtimestamp(
                    prog.get("updated_at", time.time())
                ).astimezone().isoformat(),
            }
    with SessionLocal() as db:
        lec = db.get(Lecture, lecture_id)
        if lec is None:
            status, pct, detail = "not_found", 0, "Lecture not found"
        elif lec.status == "ready":
            status, pct, detail = "ready", 100, "Ready"
        elif lec.status == "error":
            status, pct, detail = "error", 0, lec.error or "Error"
        else:
            status, pct, detail = lec.status, 50, f"Lecture status: {lec.status}"
        return {
            "lecture_id": lecture_id,
            "status": status,
            "stage": status,
            "progress_pct": pct,
            "detail": detail,
            "elapsed_s": 0.0,
            "duration_s": None,
            "updated_at": datetime.now().astimezone().isoformat(),
        }