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
            "whisper-large-v3-turbo", $0.04/audio-hour). Live-measured
            ~10x real-time (130 s wall-clock for a 21-min lecture), so a
            1-hour lecture runs in about six minutes (upload dominates).
            Audio is downmixed to mono 16 kHz FLAC and,
            if needed, split into chunks that fit the API upload limit, so
            multi-hour files work too. Rate-limited (Developer plan: 20
            req/min, 2K req/day, 7.2K audio-sec/hr); HTTP 429s back off and
            retry — they never crash the background worker.

Both return the exact same segment shape
([{"start": float, "end": float, "text": str}, ...]) so downstream
routes/db/ui are unaware of which backend produced the transcript.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

from backend.pipeline.llm import SLEEP_CAP_S, _parse_reset_seconds

BACKEND = os.getenv("WHISPER_BACKEND", "local")

# All real media is uploaded under <repo>/data/raw; anything outside that tree
# is not something this pipeline should hand to ffmpeg/Whisper.
MEDIA_ROOT = (Path(__file__).resolve().parents[2] / "data").resolve()
MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_UPLOAD_LIMIT = int(
    os.getenv("GROQ_WHISPER_UPLOAD_LIMIT", str(24 * 1024 * 1024))  # 24 MiB — conservative, auto-chunked anyway
)
# Hard per-request duration cap. Groq's Whisper can return HTTP 500 on some
# longer single chunks (observed at ~560 s on a 21-min lecture), even though
# shorter slices of the same audio pass — so split unconditionally to a
# proven-safe length. Tune with GROQ_WHISPER_MAX_CHUNK_S.
GROQ_MAX_CHUNK_S = int(os.getenv("GROQ_WHISPER_MAX_CHUNK_S", "300"))
MAX_TRANSCRIBE_RETRIES = int(os.getenv("LECGAP_WHISPER_RETRIES", "2"))
TRANSCRIBE_500_BACKOFF_S = float(os.getenv("LECGAP_WHISPER_500_BACKOFF", "5"))

_model_cache: Dict[str, object] = {}


def _get_model():
    """Lazy-load Whisper once per process; weights stay cached between calls."""
    if MODEL_SIZE not in _model_cache:
        import whisper

        _model_cache[MODEL_SIZE] = whisper.load_model(MODEL_SIZE)
    return _model_cache[MODEL_SIZE]


def _ffmpeg_available() -> bool:
    return all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe"))


def _validate_media_path(media_path: str) -> str:
    """Reject unsafe media paths before they reach ffmpeg or Whisper.

    Two vectors are guarded (SECURITY_AUDIT #5):
    - a value beginning with ``-`` would be parsed by ffmpeg as a flag;
    - a real file that resolves outside the repo ``data/`` tree (symlink or
      traversal) must not be processed.

    Non-existent paths are returned unchanged so unit tests can pass stubs;
    the upload endpoint already bounds the on-disk destination under
    ``data/raw``.
    """
    if not isinstance(media_path, (str, os.PathLike)):
        raise ValueError("media_path must be a filesystem path")
    path = str(media_path).strip()
    if not path or "\x00" in path or path.startswith("-"):
        raise ValueError(f"unsafe media path: {media_path!r}")
    p = Path(path)
    if p.exists():
        resolved = p.resolve()
        try:
            resolved.relative_to(MEDIA_ROOT)
        except ValueError:
            raise ValueError(f"media path outside data/: {media_path!r}")
    return path


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


def _detect_silence_offset(flac_path: str, target_s: float, window_s: float = 3.0) -> float:
    """Detect a silence/pause boundary near target_s to avoid clipping spoken words."""
    start_search = max(0.0, target_s - window_s)
    dur_search = window_s * 2.0
    try:
        out = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-v", "info",
                "-ss", f"{start_search:.3f}", "-t", f"{dur_search:.3f}",
                "-i", flac_path,
                "-af", "silencedetect=noise=-30dB:d=0.3",
                "-f", "null", "-",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        matches = re.findall(r"silence_start:\s*([\d\.]+)", out.stderr or "")
        if matches:
            best = min(float(m) for m in matches if abs(float(m) - window_s) <= window_s)
            return start_search + best
    except Exception:
        pass
    return target_s


def _split_flac(flac_path: str, chunk_dir: str, chunk_s: int,
                duration: float = 0.0, snap_silence: bool = False) -> List[Tuple[str, float]]:
    """Slice a FLAC into adjacent chunk_s-second pieces, returning ``(path, start_offset)`` pairs.

    Each piece is a clean, freshly-encoded standalone FLAC (seek + re-encode),
    NOT an ffmpeg ``-f segment`` cut: segmentation leaves the trailing piece in
    a shape Groq's parser rejects with HTTP 500, even though the same audio
    passes when re-encoded (observed on a 21-min lecture). Per-piece encoding
    guarantees every chunk is a byte-valid FLAC document.

    The second element of each pair is the chunk's real absolute start offset.
    Callers must use it — not ``i * chunk_s`` — to place transcribed segments,
    because snapping (``snap_silence`` / ``LECGAP_SNAP_SILENCE``) moves
    boundaries to detected pauses, so chunk starts are not uniform.
    """
    if not duration:
        duration = _probe_duration(flac_path)
    snap = snap_silence or os.getenv("LECGAP_SNAP_SILENCE", "").strip().lower() in {"1", "true", "yes"}
    chunks: List[Tuple[str, float]] = []
    start = 0.0
    idx = 0
    while start < duration:
        target_end = min(start + float(chunk_s), duration)
        if snap and target_end < duration and (duration - target_end) > 15.0:
            split_point = _detect_silence_offset(flac_path, target_end, window_s=3.0)
            split_point = max(start + 30.0, min(start + float(chunk_s) + 5.0, split_point))
        else:
            split_point = target_end
        t = split_point - start
        path = os.path.join(chunk_dir, f"chunk_{idx:03d}.flac")
        out = subprocess.run(
            [
                "ffmpeg", "-y", "-nostdin", "-v", "error",
                "-ss", f"{start:.3f}", "-t", f"{t:.3f}",
                "-i", flac_path, "-c:a", "flac", path,
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if out.returncode != 0 or not os.path.exists(path):
            raise RuntimeError(f"ffmpeg chunking failed: {out.stderr.strip()}")
        chunks.append((path, start))
        start = split_point
        idx += 1
    if not chunks:
        raise RuntimeError("ffmpeg chunking produced no files")
    return chunks


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
    failing the lecture row. HTTP 500s (Groq audio backend flakiness on some
    chunk shapes) are retried with a fixed backoff TOO, since they are
    transient in practice. Retry count via LECGAP_WHISPER_RETRIES (default 2
    re-attempts).
    """
    from groq import InternalServerError, RateLimitError

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
        except InternalServerError as exc:
            last_error = exc
            if attempt == MAX_TRANSCRIBE_RETRIES:
                raise RuntimeError(
                    "Groq Whisper returned HTTP 500 repeatedly. "
                    "Let it cool down, or switch WHISPER_BACKEND=local for the offline backend."
                ) from exc
            time.sleep(TRANSCRIBE_500_BACKOFF_S)
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


def _transcribe_groq(
    media_path: str, progress_callback=None
) -> List[Dict[str, float | str]]:
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

    if progress_callback:
        progress_callback("probing", 5, "Probing audio duration with ffprobe...")

    client = Groq()
    with tempfile.TemporaryDirectory(prefix="lecgap_groq_") as tmp:
        if progress_callback:
            progress_callback("downmixing", 15, "Normalizing audio to 16 kHz mono FLAC...")
        flac = _downmix_to_flac(media_path, os.path.join(tmp, "audio.flac"))
        size = os.path.getsize(flac)
        duration = _probe_duration(flac)

        chunk_s = _chunk_seconds(duration, size, GROQ_UPLOAD_LIMIT,
                                 max_s=GROQ_MAX_CHUNK_S)
        if chunk_s:
            if progress_callback:
                progress_callback(
                    "chunking", 25,
                    f"Audio length: {duration:.0f}s. Slicing into clean {chunk_s}s chunks...",
                )
            chunks = _split_flac(flac, tmp, chunk_s, duration)
        else:
            chunks = [(flac, 0.0)]

        total_chunks = len(chunks)
        segments: List[Dict[str, float | str]] = []
        for idx, (chunk, offset) in enumerate(chunks):
            if progress_callback:
                pct = 30 + int(60 * idx / total_chunks)
                progress_callback(
                    "transcribing", pct,
                    f"Transcribing chunk {idx + 1} of {total_chunks} via Groq Whisper...",
                )
            segments.extend(_transcribe_chunk(client, chunk, offset))
        if progress_callback:
            progress_callback(
                "finalizing", 95, f"Extracted {len(segments)} timestamped segments."
            )
    return segments


def transcribe(
    media_path: str,
    backend: str = None,
    progress_callback=None,
) -> List[Dict[str, float | str]]:
    """
    Transcribe a media file (any format ffmpeg can read) into segments:
        [{"start": 14.22, "end": 17.10, "text": "..."}, ...]

    ``backend`` overrides the WHISPER_BACKEND env pick for this call ("groq" or
    "local"). When nothing pins a backend, groq is auto-selected if
    GROQ_API_KEY is set AND ffmpeg is on PATH (hosted Whisper runs ~200x
    real-time); otherwise the offline Whisper path is used.
    """
    selected_backend = backend or BACKEND
    media_path = _validate_media_path(media_path)
    if not backend and not os.getenv("WHISPER_BACKEND") and os.getenv("GROQ_API_KEY"):
        if _ffmpeg_available():
            selected_backend = "groq"
        elif progress_callback:
            progress_callback(
                "loading_model", 20,
                "GROQ_API_KEY set but ffmpeg/ffprobe missing on PATH — using local Whisper.",
            )

    if selected_backend == "groq":
        return _transcribe_groq(media_path, progress_callback=progress_callback)

    if progress_callback:
        progress_callback(
            "loading_model", 20, f"Loading Whisper model '{MODEL_SIZE}' on CPU..."
        )
    model = _get_model()
    if progress_callback:
        progress_callback(
            "local_transcribing", 50,
            "Transcribing with Whisper on CPU (this takes time for long audio)...",
        )
    result = model.transcribe(media_path, verbose=False)
    if progress_callback:
        progress_callback(
            "finalizing", 95, f"Extracted {len(result['segments'])} segments."
        )
    return [
        {
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": seg["text"].strip(),
        }
        for seg in result["segments"]
    ]