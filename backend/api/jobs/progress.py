"""Live per-lecture job progress — the store read by GET /lectures/{id}/progress.

Workers publish stages here; routes reply from it. Entries are pruned on a
job's final state (ready/error) so long-lived processes don't leak, and
gets fall back to a DB-derived snapshot once a job has ended.
"""

from datetime import datetime
import threading
import time

from backend.models.db import Lecture, SessionLocal

_progress_lock = threading.Lock()
_lecture_progress: dict = {}


def update_lecture_progress(
    lecture_id: int, stage: str, pct: int, detail: str, status: str = "transcribing",
    duration_s: float = None,
) -> None:
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


def _finish(lecture_id: int) -> None:
    """Drop the in-memory entry once a job settles (ready/error)."""
    with _progress_lock:
        _lecture_progress.pop(lecture_id, None)


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