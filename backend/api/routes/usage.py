"""API-usage transparency (plan/FRONTEND_ARCHITECTURE.md §10).

`GET /usage` returns per-service Groq rate-limit snapshots (chat vs whisper)
plus local/Ollama availability so the student dashboard can show how much
transcribing is left. Guarded by the API-key middleware when configured
(*contract*: like `/llm/backends`). Aggregates only — no keys ever leave.
"""

from fastapi import APIRouter

from backend.api import usage
from backend.config import GROQ_MODEL, GROQ_WHISPER_MODEL
from backend.pipeline.llm import backend_status_detailed
from backend.pipeline.transcribe import _ffmpeg_available

router = APIRouter()


@router.get("/usage")
def get_usage() -> dict:
    detailed = backend_status_detailed()
    return {
        "services": usage.snapshot(
            groq_model=GROQ_MODEL,
            whisper_model=GROQ_WHISPER_MODEL,
            local_available=True,  # bundled Whisper always present
            ffmpeg_ok=_ffmpeg_available(),
            ollama_reachable=detailed.get("ollama_reachable", False),
        )["services"],
        "availability": detailed,
    }