"""
Stage 5 — Clip Segmentation
See plan/ARCHITECTURE.md, Stage 5.

Cuts one clip per concept per timestamp range using FFmpeg. Standard
infrastructure (no ML claim here), and pure — like the other pipeline
modules it does not touch the DB; the API layer persists the `clips` rows.

  cut_clip(media_path, start, end, out_path)
      -> ffmpeg subprocess call for a single [start, end) segment.

  cut_concept_clips(media_path, concepts, out_dir)
      -> one clip per concept; returns per-concept results so the caller can
         record which succeeded and which were cut (start/end optional).

Clips land under data/processed/clips/<lecture_id>/ so the remediation loop
(Stage 6/7) can play them back in dependency order.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

# Re-encoding to H.264/AAC is slow on CPU; using stream copy ("-c copy")
# keeps Stage 5 instant and lossless for our clip-cuts. Overriding tool
# flags is possible via the `ffmpeg` binary path.
_COPY_ARGS = ["-c", "copy"]

_INVALID_CHARS = re.compile(r"[^\w\- .]")


def _safe_name(name: str) -> str:
    """Filesystem-safe concept name (clip filename stem)."""
    cleaned = _INVALID_CHARS.sub("_", str(name).strip())
    return cleaned or "concept"


def _validate_times(start_s, end_s) -> List[float]:
    start = float(start_s)
    end = float(end_s)
    if start < 0.0:
        raise ValueError(f"start_s must be >= 0, got {start}")
    if end <= start:
        raise ValueError(f"end_s ({end}) must be > start_s ({start})")
    return [start, end]


def cut_clip(
    media_path: str,
    start_s,
    end_s,
    out_path: str,
    *,
    ffmpeg: str = "ffmpeg",
) -> Dict:
    """Cut a single [start_s, end_s) segment from media_path into out_path.

    Returns {"media": ..., "start_s": ..., "end_s": ..., "out_path": ...,
    "ok": bool, "cmd": str, "error": Optional[str]}. Raises ValueError on
    malformed times. Bare ffmpeg returncode is surfaced via `error` so one
    bad clip doesn't abort a whole lecture.
    """
    start, end = _validate_times(start_s, end_s)
    media_path = str(media_path)
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", media_path]
    cmd += _COPY_ARGS + [out_path]
    cmd_str = " ".join(cmd)

    try:
        result = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=300
        )
    except subprocess.TimeoutExpired:
        return {
            "media": media_path, "start_s": start, "end_s": end,
            "out_path": out_path, "ok": False, "cmd": cmd_str,
            "error": "ffmpeg timed out",
        }
    except FileNotFoundError:
        return {
            "media": media_path, "start_s": start, "end_s": end,
            "out_path": out_path, "ok": False, "cmd": cmd_str,
            "error": f"ffmpeg executable not found: {ffmpeg!r}",
        }

    return {
        "media": media_path, "start_s": start, "end_s": end,
        "out_path": out_path, "ok": result.returncode == 0,
        "cmd": cmd_str,
        "error": None if result.returncode == 0
        else (result.stderr or result.stdout or "").strip()[:2000],
    }


def cut_concept_clips(
    media_path: str,
    concepts: List[Dict],
    out_dir: str,
    *,
    ffmpeg: str = "ffmpeg",
) -> List[Dict]:
    """Cut one clip per concept into out_dir.

    `concepts` is a list of dicts each with at least {"name": str, "start_s":
    float, "end_s": float}. Returns a list (same order) of per-concept results
    with the clip path; concepts missing start/end are reported as skipped
    (ok=False, error="missing timestamps") rather than crashing the batch.

    output written as: out_dir/<safe name>__<start>-<end>.mp4
    """
    out_dir = str(out_dir)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results: List[Dict] = []

    for concept in concepts:
        name = _safe_name(concept.get("name", ""))
        start_s = concept.get("start_s")
        end_s = concept.get("end_s")
        if start_s is None or end_s is None:
            results.append(
                {
                    "name": concept.get("name"),
                    "start_s": None, "end_s": None, "path": None,
                    "ok": False, "error": "missing timestamps",
                }
            )
            continue
        start, end = float(start_s), float(end_s)
        out_path = str(Path(out_dir) / f"{name}__{start:.0f}-{end:.0f}.mp4")
        res = cut_clip(media_path, start, end, out_path, ffmpeg=ffmpeg)
        res["name"] = concept.get("name")
        res["path"] = out_path if res["ok"] else None
        results.append(res)

    return results
