"""
Central configuration — the single source of truth for the runtime's env surface.

Every environment variable the serving system reads flows through this module,
so exactly one file has to answer "what does the app read from the environment,
and with what defaults/typing?" Keep ``.env.example`` in sync when a key is
added or a default changes.

Two ways in:

  * Import-time values (the models/route constants frozen at process start)
    are exported as module constants below — same read timing as before.
  * Values that should reflect a runtime change to the environment use the
    lazy getter functions inside the code that calls them (``groq_api_key()``
    etc.). Use the typed getters (``get_int`` / ``get_float`` / ``get_bool``)
    so parsing and bounds-checking live in exactly one file.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Shared artifact tree (one formula, defined once; routes + jobs reference it).
MEDIA_ROOT_DIR = REPO_ROOT / "data" / "raw"
CLIPS_BASE_DIR = REPO_ROOT / "data" / "processed" / "clips"


# ------------------------------------------------------------- typed getters

def get_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() if name in os.environ else default


def get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def get_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


# ------------------------------------------------------- lazy (call-time) keys

def api_key() -> str:
    """LECGAP_API_KEY — bearer/YAML-style auth secret; empty means 'open'."""
    return get_str("LECGAP_API_KEY")


def groq_api_key() -> str:
    return get_str("GROQ_API_KEY")


def llm_reasoning_enabled() -> bool:
    return get_bool("LECGAP_LLM_REASONING")


def snap_silence_enabled() -> bool:
    return get_bool("LECGAP_SNAP_SILENCE")


def clip_streamcopy_enabled() -> bool:
    return get_bool("LECGAP_CLIP_STREAMCOPY")


def clip_reencode_threshold_s() -> float:
    return get_float("LECGAP_CLIP_REENCODE_THRESHOLD_S", 120.0)


def clip_workers() -> int | None:
    """LECGAP_CLIP_WORKERS, validated; None means 'auto' (use logical cores)."""
    raw = get_str("LECGAP_CLIP_WORKERS")
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def whisper_backend_override() -> str:
    """WHISPER_BACKEND as explicitly set (empty when unconfigured)."""
    return get_str("WHISPER_BACKEND")


# --------------------------------------------------- import-time (frozen) keys

# Database (backend/models/db.py). The pragma listener keys on the scheme,
# so keep the sqlite:// default shape unchanged.
DATABASE_URL = get_str(
    "LECGAP_DATABASE_URL", f"sqlite:///{REPO_ROOT / 'data' / 'lecgap.db'}"
)

# Upload cap (MiB) — 0 disables the cap for local use (backend/api/routes/lectures.py).
MAX_UPLOAD_MB = get_int("LECGAP_MAX_UPLOAD_MB", 2048)

# Concurrent heavy pipeline jobs — >= 1 (backend/api/jobs/common.py).
MAX_PIPELINE_JOBS = max(1, get_int("LECGAP_MAX_PIPELINE_JOBS", 3))

# LLM gateway (backend/pipeline/llm.py).
GROQ_MODEL = get_str("LECGAP_GROQ_MODEL", "openai/gpt-oss-20b")
OLLAMA_MODEL = get_str("LECGAP_OLLAMA_MODEL", "llama3.2")
OLLAMA_BASE_URL = get_str("LECGAP_OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MAX_RETRIES = get_int("LECGAP_LLM_RETRIES", 2)
LLM_SLEEP_CAP_S = get_float("LECGAP_LLM_SLEEP_CAP_S", 120.0)
LLM_CACHE_TTL_S = get_float("LECGAP_LLM_CACHE_TTL_S", 30 * 24 * 3600)

# Hub encoder pinning (backend/pipeline/model_ids.py).
EMBEDDING_MODEL = get_str(
    "LECGAP_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
EMBEDDING_REVISION = get_str("LECGAP_EMBEDDING_REVISION") or None

# Lecture-structure pass (backend/pipeline/passages.py).
STRUCTURE_WINDOW_CHARS = get_int("LECGAP_STRUCTURE_WINDOW_CHARS", 8000)
STRUCTURE_OVERLAP_FRAC = get_float("LECGAP_STRUCTURE_OVERLAP_FRAC", 0.25)
STRUCTURE_MAX_TOKENS = get_int("LECGAP_STRUCTURE_MAX_TOKENS", 3000)

# Transcription (backend/pipeline/transcribe.py).
WHISPER_BACKEND = get_str("WHISPER_BACKEND", "local")
WHISPER_MODEL = get_str("WHISPER_MODEL", "base")
GROQ_WHISPER_MODEL = get_str("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
GROQ_WHISPER_UPLOAD_LIMIT = get_int("GROQ_WHISPER_UPLOAD_LIMIT", 24 * 1024 * 1024)
GROQ_WHISPER_MAX_CHUNK_S = get_int("GROQ_WHISPER_MAX_CHUNK_S", 300)
WHISPER_MAX_RETRIES = get_int("LECGAP_WHISPER_RETRIES", 2)
WHISPER_500_BACKOFF_S = get_float("LECGAP_WHISPER_500_BACKOFF", 5.0)