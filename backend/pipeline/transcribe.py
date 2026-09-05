"""
Stage 1 — Transcription
See plan/ARCHITECTURE.md, Stage 1.

Takes a raw lecture audio/video file and produces timestamped transcript
segments using Whisper. Pure infrastructure — no ML claim lives here.

Two backends, chosen with the WHISPER_BACKEND env var:

    local   openai-whisper running locally (WHISPER_MODEL, default "base").
            Zero quota, no network, slower (~1.3x real-time for base on CPU).
            This is the default so tests and offline teampates never touch
            the network or burn quota.

    groq    hosted Whisper on Groq's LPU (GROQ_WHISPER_MODEL, default
            "whisper-large-v3-turbo", $0.04/audio-hour). ~216x real-time, so
            a 1-hour lecture transcribes in roughly a minute of wall-clock
            (upload dominates). Audio is downmixed to mono 16 kHz FLAC and,
            if needed, split into chunks that fit the API upload limit, so
            multi-hour files work too. Rate-limited (Developer plan: 20
            req/min, 2K req/day, 7.2K audio-sec/hr); HTTP 429s back off and
            retry — they never crash the background worker.

Both return the exact same segment shape
([{"start": float, "end": float, "text": str}, ...]) so downstream
routes/db/ui are unaware of which backend produced the transcript.
"""

import os
import shutil
import subprocess
import tempfile
import time
from typing import Dict, List

from backend.pipeline.llm import SLEEP_CAP_S, _parse_reset_seconds

BACKEND = os.getenv("WHISPER_BACKEND", "local")
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_UPLOAD_LIMIT = int(
    os.getenv("GROQ_WHISPER_UPLOAD_LIMIT", str(24 * 1024 * 1024))  # 24 MiB — conservative, auto-chunked anyway
)
MAX_TRANSCRIBE_RETRIES = int(os.getenv("LECGAP_WHISPER_RETRIES", "2"))

_model_cache: Dict[str, object] = {}


def _get_model():
    """Lazy-load Whisper once per process; weights stay cached between calls."""
    if MODEL_SIZE not in _model_cache:
        import whisper

        _model_cache[MODEL_SIZE] = whisper.load_model(MODEL_SIZE)
    return _model_cache[MODEL_SIZE]


def _ffmpeg_available() -> bool:
    return all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe"))


def _probe_duration(media_path: str) -> float:
    """Return media duration in seconds via ffprobe."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", media_path,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {out.stderr.strip()}")
    return float(out.stdout.strip())


def _chunk_seconds(duration_s: float, size_bytes: int, upload_limit: int,
                   min_s: int = 20, max_s: int = 900) -> int:
    """
    Pick a chunk length that keeps each FLAC chunk under the upload limit.
    Returns chunk length in seconds, or 0 when the file already fits.
    """
    if not duration_s or not size_bytes:
        return 0
    bytes_per_sec = size_bytes / duration_s
    target_bytes = int(upload_limit * 0.8)
    want = int(target_bytes / bytes_per_sec) if bytes_per_sec else max_s
    return max(min(want, max_s), min_s) if want < duration_s else 0


def _downmix_to_flac(src: str, dst_flac: str) -> str:
    """Normalise to mono 16 kHz FLAC (per Groq's best-practice upload format)."""
    out = subprocess.run(
        [
            "ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1",
            "-map", "0:a", "-c:a", "flac", dst_flac,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg downmix failed: {out.stderr.strip()}")
    return dst_flac


def _split_flac(flac_path: str, chunk_dir: str, chunk_s: int) -> List[str]:
    """Slice a FLAC into adjacent chunk_s-second pieces, returning sorted paths."""
    out = subprocess.run(
        [
            "ffmpeg", "-y", "-i", flac_path, "-f", "segment",
            "-segment_time", str(chunk_s), "-reset_timestamps", "1",
            "-c:a", "flac", os.path.join(chunk_dir, "chunk_%03d.flac"),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg chunking failed: {out.stderr.strip()}")
    chunks = sorted(
        p for p in os.listdir(chunk_dir) if p.startswith("chunk_") and p.endswith(".flac")
    )
    if not chunks:
        raise RuntimeError("ffmpeg chunking produced no files")
    return [os.path.join(chunk_dir, c) for c in chunks]


def _seg_bounds(seg) -> tuple:
    """Extract (start, end, text) from a Groq segment, which may be a dict
    (current SDK) or an attribute-style object (older/newer SDK shapes)."""
    if isinstance(seg, dict):
        return float(seg["start"]), float(seg["end"]), str(seg["text"] or "").strip()
    return float(seg.start), float(seg.end), str(getattr(seg, "text", "") or "").strip()


def _transcribe_chunk(client, chunk_path: str, offset: float) -> List[Dict[str, float | str]]:
    """Transcribe one chunk with Groq and shift timestamps by the chunk offset.

    HTTP 429 (rate limit) is retried with respect for Groq's reset header
    (mirrors llm._call_groq), so bursty build/test uploads back off instead of
    failing the lecture row. Retry count via LECGAP_WHISPER_RETRIES (default 2
    re-attempts).
    """
    from groq import RateLimitError

    resp = None
    last_error = None
    for attempt in range(MAX_TRANSCRIBE_RETRIES + 1):
        try:
            with open(chunk_path, "rb") as fh:
                resp = client.audio.transcriptions.create(
                    model=GROQ_WHISPER_MODEL,
                    file=(os.path.basename(chunk_path), fh),
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
            break
        except RateLimitError as exc:
            last_error = exc
            reset = 60.0
            try:
                reset = _parse_reset_seconds(
                    exc.response.headers.get("x-ratelimit-reset-requests", "60s")
                )
            except Exception:
                pass
            if attempt == MAX_TRANSCRIBE_RETRIES or reset > SLEEP_CAP_S:
                raise RuntimeError(
                    f"Groq Whisper rate limit exhausted (window resets in {reset:.0f}s). "
                    "Wait, or switch WHISPER_BACKEND=local for the offline backend."
                ) from exc
            time.sleep(min(reset, SLEEP_CAP_S))
    if resp is None:
        raise RuntimeError(f"Groq Whisper call failed after retries: {last_error}")

    segments = getattr(resp, "segments", None)
    if not segments:
        segments = [
            {
                "start": 0.0,
                "end": _probe_duration(chunk_path),
                "text": getattr(resp, "text", "") or "",
            }
        ]

    return [
        {"start": start + offset, "end": end + offset, "text": text}
        for start, end, text in (_seg_bounds(seg) for seg in segments)
    ]


def _transcribe_groq(media_path: str) -> List[Dict[str, float | str]]:
    if not os.getenv("GROQ_API_KEY"):
        raise RuntimeError(
            "WHISPER_BACKEND=groq needs GROQ_API_KEY set (see .env). "
            "Set WHISPER_BACKEND=local to use the offline backend."
        )
    if not _ffmpeg_available():
        raise RuntimeError(
            "WHISPER_BACKEND=groq needs ffmpeg + ffprobe on PATH. "
            "Set WHISPER_BACKEND=local to use the offline backend."
        )

    from groq import Groq

    client = Groq()
    with tempfile.TemporaryDirectory(prefix="lecgap_groq_") as tmp:
        flac = _downmix_to_flac(media_path, os.path.join(tmp, "audio.flac"))
        size = os.path.getsize(flac)
        duration = _probe_duration(flac)

        chunk_s = _chunk_seconds(duration, size, GROQ_UPLOAD_LIMIT)
        if chunk_s:
            chunks = _split_flac(flac, tmp, chunk_s)
            offsets = [float(i * chunk_s) for i in range(len(chunks))]
        else:
            chunks, offsets = [flac], [0.0]

        segments: List[Dict[str, float | str]] = []
        for chunk, offset in zip(chunks, offsets):
            segments.extend(_transcribe_chunk(client, chunk, offset))
    return segments


def transcribe(media_path: str) -> List[Dict[str, float | str]]:
    """
    Transcribe a media file (any format ffmpeg can read) into segments:
        [{"start": 14.22, "end": 17.10, "text": "..."}, ...]
    """
    if BACKEND == "groq":
        return _transcribe_groq(media_path)

    model = _get_model()
    result = model.transcribe(media_path, verbose=False)
    return [
        {
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": seg["text"].strip(),
        }
        for seg in result["segments"]
    ]