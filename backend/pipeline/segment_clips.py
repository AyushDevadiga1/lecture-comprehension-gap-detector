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

import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

# Clip cuts default to a hybrid. Re-encoding to H.264/AAC makes the video
# start exactly on the requested frame; stream copy ("-c copy") is instant and
# lossless but snaps back to the prior keyframe (2-6s typical GOP), freezing
# the first visually decoded frame. For concept clips (typically 15-60s),
# frame-accuracy is critical, so spans at or under LECGAP_CLIP_REENCODE_THRESHOLD_S
# (default 120s) re-encode. Very long spans stream-copy to save CPU.
# LECGAP_CLIP_STREAMCOPY=1 forces every clip into the fast copy path.
_RENDER_ARGS = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
    "-c:a", "aac", "-b:a", "96k",
    "-movflags", "+faststart",
]

from backend.config import (
    clip_reencode_threshold_s,
    clip_streamcopy_enabled,
    clip_workers,
)


def _codec_args(span_s=None) -> List[str]:
    if clip_streamcopy_enabled():
        return ["-c", "copy"]
    if span_s is not None and span_s > clip_reencode_threshold_s():
        return ["-c", "copy"]
    return _RENDER_ARGS

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


def _resolve_ffmpeg() -> str:
    """Resolve the ffmpeg executable strictly from PATH.

    SECURITY_AUDIT #6: never let a caller pass an arbitrary executable path —
    an internal caller forwarding user input could otherwise execute any
    binary. Falls back to the bare name so the FileNotFoundError path still
    reports a useful error.
    """
    return shutil.which("ffmpeg") or "ffmpeg"


def cut_clip(
    media_path: str,
    start_s,
    end_s,
    out_path: str,
) -> Dict:
    """Cut a single [start_s, end_s) segment from media_path into out_path.

    Start/end may be floats; re-encode-vs-copy is decided per span by
    _codec_args (short clips stream-copy, long clips re-encode for
    keyframe-accurate starts). Returns {"media": ..., "start_s": ...,
    "end_s": ..., "out_path": ..., "ok": bool, "cmd": str, "error":
    Optional[str]}. Raises ValueError on malformed times. Bare ffmpeg
    returncode is surfaced via `error` so one bad clip doesn't abort a whole
    lecture.
    """
    start, end = _validate_times(start_s, end_s)
    media_path = str(media_path)
    out_path = str(out_path)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _resolve_ffmpeg()
    cmd = [ffmpeg, "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", media_path]
    cmd += _codec_args(end - start) + [out_path]
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


def _default_workers() -> int:
    """Concurrent clip cuts. Each ffmpeg process is its own CPU-bound decode
    + libx264 encode, so tiling them across cores is a near-linear wall-clock
    win. LECGAP_CLIP_WORKERS overrides; default = min(4, logical cores)."""
    env = clip_workers()
    if env is not None:
        return env
    return max(1, min(4, (os.cpu_count() or 1)))


def cut_concept_clips(
    media_path: str,
    concepts: List[Dict],
    out_dir: str,
    *,
    max_workers: Optional[int] = None,
    on_done=None,
) -> List[Dict]:
    """Cut one clip per concept into out_dir.

    `concepts` is a list of dicts each with at least {"name": str, "start_s":
    float, "end_s": float}. Returns a list (same order) of per-concept results
    with the clip path; concepts missing start/end are reported as skipped
    (ok=False, error="missing timestamps") rather than crashing the batch.

    `on_done(done, total)` is called after each clip finishes (skipped clips
    included) so callers can surface live progress.

    Cuts run concurrently (one ffmpeg subprocess per clip, up to `max_workers`
    or the LECGAP_CLIP_WORKERS/default worker count) because the re-encoding
    cost is CPU-bound; on a 4-core machine 51 clips drop from ~25 min to
    ~6 min. Each clip still uses input-side `-ss` fast seek, so frame
    accuracy is unchanged from the serial path.

    output written as: out_dir/<safe name>__<start>-<end>.mp4
    """
    out_dir = str(out_dir)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_root = Path(out_dir).resolve()
    results: List[Dict] = [None] * len(concepts)
    jobs: List[tuple] = []  # (index_in_concepts, concept, out_path)

    for i, concept in enumerate(concepts):
        name = _safe_name(concept.get("name", ""))
        start_s = concept.get("start_s")
        end_s = concept.get("end_s")
        if start_s is None or end_s is None:
            results[i] = {
                "name": concept.get("name"),
                "start_s": None, "end_s": None, "path": None,
                "ok": False, "error": "missing timestamps",
            }
            if on_done:
                on_done(1, len(concepts))
            continue
        start, end = float(start_s), float(end_s)
        out_path = str(Path(out_dir) / f"{name}__{start:.0f}-{end:.0f}.mp4")
        # SECURITY_AUDIT #6: never let a crafted concept name escape out_dir.
        try:
            Path(out_path).resolve().relative_to(out_root)
        except ValueError:
            results[i] = {
                "name": concept.get("name"),
                "start_s": start, "end_s": end, "path": None,
                "ok": False, "error": "unsafe clip output path",
            }
            if on_done:
                on_done(1, len(concepts))
            continue
        jobs.append((i, concept, out_path))

    if not jobs:
        if on_done and len(concepts) > 1:
            on_done(len(concepts), len(concepts))
        return results

    done_count = len(concepts) - len(jobs)  # skipped clips count as done too

    def run_cut(args: tuple) -> tuple:
        i, concept, out_path = args
        res = cut_clip(media_path, concept["start_s"], concept["end_s"], out_path)
        res["name"] = concept.get("name")
        res["path"] = out_path if res["ok"] else None
        return i, res

    def harvest(i: int, res: dict) -> None:
        results[i] = res
        nonlocal done_count
        done_count += 1
        if on_done:
            on_done(done_count, len(concepts))

    workers = max_workers if max_workers is not None else _default_workers()
    if workers > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for i, res in pool.map(run_cut, jobs):
                harvest(i, res)
    else:
        for i, res in map(run_cut, jobs):
            harvest(i, res)

    return results
