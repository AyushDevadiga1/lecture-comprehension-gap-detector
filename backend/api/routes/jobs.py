"""Job registry endpoints — list, read, cancel, and a live SSE stream.

The stream is the point of C2. While a job runs, the frontend used to
re-render the entire page every 0.5-1.5s to read a progress number, which
restarted every video player and made the page thrash. A server-sent event
carries the same information without re-rendering anything.
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.api import job_registry as registry
from backend.api.schemas import JobOut, JobListOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _validate_course_id(course_id: str) -> str:
    import re
    if not re.fullmatch(r"^[\w\-]{1,128}$", course_id or ""):
        raise HTTPException(status_code=422, detail="Invalid course_id")
    return course_id


@router.get("", response_model=JobListOut)
def list_jobs(course_id: str = None, limit: int = Query(100, ge=1, le=500),
              active_only: bool = False) -> JobListOut:
    """Every job, optionally scoped to a course.

    Deliberately not scoped to a session: the whole point is that a second
    browser sees what the first one started.
    """
    if course_id:
        _validate_course_id(course_id)
    jobs = registry.list_jobs(course_id=course_id, limit=limit,
                              active_only=active_only)
    return JobListOut(jobs=jobs)


async def event_stream(course_id: str = None, interval_s: float = 1.0):
    """Yield server-sent event chunks for the given course.

    Emits only on change - a full snapshot on connect, then diffs - so an idle
    course costs one cheap query per interval and nothing when nothing moves.
    Kept as a module-level generator so it can be driven directly in tests
    without an endless HTTP body.
    """
    last = None
    # let the browser paint the page before the stream opens, so the connection
    # never competes with first render
    yield "retry: 2000\n\n"
    while True:
        jobs = await asyncio.to_thread(registry.list_jobs,
                                      course_id=course_id, limit=100)
        snapshot = json.dumps(jobs, default=str)
        if snapshot != last:
            last = snapshot
            yield f"event: jobs\ndata: {snapshot}\n\n"
        else:
            # keep-alive so proxies do not drop an idle connection
            yield ": keep-alive\n\n"
        await asyncio.sleep(interval_s)


@router.get("/stream")
async def stream_jobs(course_id: str = None,
                      interval_s: float = Query(1.0, ge=0.25, le=30.0)):
    """Server-sent events carrying job state changes.

    The stream is the point of C2. While a job runs, the frontend used to
    re-render the entire page every 0.5-1.5s to read a progress number, which
    restarted every video player and made the page thrash. An event carries the
    same information without re-rendering anything.
    """
    if course_id:
        _validate_course_id(course_id)
    return StreamingResponse(
        event_stream(course_id, interval_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int) -> JobOut:
    job = registry.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut(**job)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int) -> JobOut:
    """Mark a job cancelled.

    Honest about what it can do: a job already executing in a worker thread
    cannot be interrupted, so this settles the record and the worker's own
    terminal write is ignored afterwards.
    """
    job = registry.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["terminal"]:
        raise HTTPException(
            status_code=409,
            detail=f"Job already finished with status '{job['status']}'.")
    registry.finish_job(
        job_id, status="cancelled",
        detail="Cancelled by the user. If it was mid-flight the work may still "
               "finish in the background.")
    return JobOut(**registry.get_job(job_id))
