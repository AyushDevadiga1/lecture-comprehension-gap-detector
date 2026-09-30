"""The job registry (Engine 2, C2) — persisted, restart-safe background work.

The process-memory progress store this replaces could not answer three
questions the UI needs:

  * is the job still alive? -> ``heartbeat_at``
  * what happened to it if the server died? -> ``orphaned``, assigned at boot
  * who else is watching it? -> progress is keyed by ``job_id``, and
    ``GET /jobs?course_id=`` lists every job on a course regardless of which
    session started it.

The per-course advisory lock lives here too, so two users cannot interleave
extraction / clip / graph work on the same course and fight over the same rows.
"""

import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from backend.models.db import Job, SessionLocal

_LOGGER = logging.getLogger("lecgap.jobs.registry")

# A job whose heartbeat is older than this was, in all likelihood, killed by a
# process that went away. Generous: a long ffmpeg re-encode or a MiniLM cold
# load can be quiet for minutes, and a false "orphaned" would be a lie.
ORPHAN_AFTER_S = 15 * 60

TERMINAL = ("ready", "error", "orphaned", "cancelled")

_locks: dict = {}
_locks_guard = threading.Lock()


def _course_lock(course_id: str) -> threading.Lock:
    """Advisory per-course lock: one heavy job per course at a time."""
    if not course_id:
        return _NULL_LOCK
    with _locks_guard:
        lock = _locks.get(course_id)
        if lock is None:
            lock = _locks[course_id] = threading.Lock()
        return lock


class _NullLock:
    """Stands in for the per-course lock when there is no course.

    Implements the same acquire/release surface as ``threading.Lock`` so callers
    never need to special-case it.
    """

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return True

    def release(self) -> None:
        return None

    def locked(self) -> bool:
        return False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NULL_LOCK = _NullLock()


def _now():
    return datetime.now(timezone.utc)


def _as_utc(dt):
    """SQLite drops tzinfo on DATETIME columns, so a row read back is naive.

    Comparing that naive value against an aware cutoff raises TypeError, which
    would make every freshly created job look stale and get orphaned at boot.
    Treat naive as UTC, which is what it was written as.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ------------------------------------------------------------------ create

def create_job(kind: str, *, course_id: str = None, lecture_id: int = None,
               title: str = None, payload: dict = None) -> int:
    """Register a queued job and return its id."""
    now = _now()
    with SessionLocal() as db:
        job = Job(
            kind=kind,
            status="queued",
            course_id=course_id,
            lecture_id=lecture_id,
            title=title,
            stage="queued",
            detail="Waiting to start…",
            progress_pct=0,
            payload_json=json.dumps(payload) if payload else None,
            created_at=now,
            heartbeat_at=now,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.id


# ------------------------------------------------------------------ update

def update_job(job_id: int, *, stage: str = None, detail: str = None,
               progress_pct: int = None, status: str = None) -> None:
    """Publish progress. Also refreshes the heartbeat."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        now = _now()
        if stage is not None:
            job.stage = stage
        if detail is not None:
            job.detail = detail
        if progress_pct is not None:
            job.progress_pct = int(max(0, min(int(progress_pct), 100)))
        if status is not None and job.status != status:
            job.status = status
            if status == "running" and job.started_at is None:
                job.started_at = now
            if status in TERMINAL:
                job.finished_at = now
        job.heartbeat_at = now
        db.commit()


def finish_job(job_id: int, *, status: str = "ready", detail: str = None,
               error: str = None) -> None:
    """Settle a job on a terminal state."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        now = _now()
        job.status = status
        if detail is not None:
            job.detail = detail
        if error is not None:
            job.error = error
        job.finished_at = now
        job.heartbeat_at = now
        if status == "ready":
            job.progress_pct = 100
        db.commit()


def fail_job(job_id: int, error: str) -> None:
    finish_job(job_id, status="error", detail=error, error=error)


# -------------------------------------------------------------------- read

def get_job(job_id: int) -> dict:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return _serialize(job) if job else None


def list_jobs(course_id: str = None, limit: int = 100,
              active_only: bool = False) -> list:
    with SessionLocal() as db:
        q = db.query(Job)
        if course_id:
            q = q.filter(Job.course_id == course_id)
        if active_only:
            q = q.filter(~Job.status.in_(TERMINAL))
        rows = q.order_by(Job.id.desc()).limit(max(1, limit)).all()
        return [_serialize(j) for j in rows]


def _serialize(job: Job) -> dict:
    started = job.started_at
    finished = job.finished_at
    duration = None
    if started and finished:
        try:
            duration = round((finished - started).total_seconds(), 1)
        except TypeError:      # naive/aware mix from older rows
            duration = None
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "course_id": job.course_id,
        "lecture_id": job.lecture_id,
        "title": job.title,
        "stage": job.stage,
        "detail": job.detail,
        "progress_pct": job.progress_pct,
        "error": job.error,
        "created_at": _iso(job.created_at),
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "heartbeat_at": _iso(job.heartbeat_at),
        "duration_s": duration,
        "terminal": job.status in TERMINAL,
    }


def _iso(dt):
    """Serialise a stored timestamp for the wire.

    SQLite drops tzinfo on DATETIME columns, so a value read back is naive --
    and it was written as UTC (`utcnow`, on every Job column). The trap is that
    `naive.astimezone()` does not mean "this was UTC", it means "assume this is
    LOCAL time", so serialising without relabelling first shifts every timestamp
    by the machine's UTC offset.

    Measured on a +05:30 box: a job created seconds earlier was reported to the
    browser as **330 minutes old**, which is what the job drawer showed. The
    stall detector and the six-hour `JOB_DEADLINE_S` backstop inherit the same
    shift, so they misfire by 5.5 hours as well.

    Routed through `_as_utc` deliberately: the read path and the write path are
    the same rule about the same column, and they had already drifted apart once.
    `WEDGE_DIAGNOSIS_2026-09-29.md` §4 established the rule (stored values are
    UTC wall-clock, drift 0.0 minutes) and fixed the read side; the write side
    was never checked, and only surfaced by looking at a screenshot.
    """
    if dt is None:
        return None
    try:
        return _as_utc(dt).astimezone().isoformat()
    except (AttributeError, ValueError):
        return str(dt)


# ---------------------------------------------------------------- recovery

def recover_orphans(older_than_s: int = ORPHAN_AFTER_S) -> int:
    """At boot: any job left ``running`` by a dead process becomes ``orphaned``.

    This is the honest answer for work nobody is performing any more. Without
    it a restart left the UI polling a progress value that would never change.
    """
    cutoff = _now() - timedelta(seconds=older_than_s)
    n = 0
    with SessionLocal() as db:
        stale = (
            db.query(Job)
            .filter(Job.status.in_(("queued", "running")))
            .all()
        )
        for job in stale:
            beat = _as_utc(job.heartbeat_at or job.created_at)
            if beat is not None and beat > cutoff:
                continue
            job.status = "orphaned"
            job.error = job.error or (
                "The server restarted while this job was running; nothing is "
                "executing it any more.")
            job.detail = job.detail or "Interrupted by a server restart."
            job.finished_at = _now()
            n += 1
        if n:
            db.commit()
    if n:
        _LOGGER.warning("marked %d in-flight job(s) orphaned at startup", n)
    return n


# ----------------------------------------------------------------- locking

class CourseBusy(Exception):
    """Raised when another heavy job already holds the course's lock."""

    def __init__(self, course_id: str, holder_job_id: int = None):
        self.course_id = course_id
        self.holder_job_id = holder_job_id
        super().__init__(f"course {course_id!r} already has a job running")


def acquire_course(course_id: str, job_id: int = None, blocking: bool = False):
    """Take the per-course advisory lock, or raise :class:`CourseBusy`.

    Non-blocking by default: a second request gets an immediate, honest refusal
    instead of silently queueing behind minutes of work and then racing it.
    """
    lock = _course_lock(course_id)
    if not lock.acquire(blocking=blocking):
        raise CourseBusy(course_id, holder_job_id=job_id)
    return lock


def release_course(course_id: str) -> None:
    if not course_id:
        return
    lock = _course_lock(course_id)
    if lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass


def reset_locks_for_tests() -> None:
    with _locks_guard:
        _locks.clear()
