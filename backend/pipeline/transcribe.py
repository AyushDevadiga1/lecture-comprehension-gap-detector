"""
Stage 1 — Transcription
See plan/ARCHITECTURE.md, Stage 1.

Takes a raw lecture audio/video file and produces timestamped transcript
segments using Whisper. Pure infrastructure — no ML claim lives here.

This module is deliberately pure (no DB writes): persistence happens in
backend/models/db.py, orchestrated by backend/api/routes.py.
"""

import os
from typing import Dict, List

MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")

_model_cache: Dict[str, object] = {}


def _get_model():
    """Lazy-load Whisper once per process; weights stay cached between calls."""
    if MODEL_SIZE not in _model_cache:
        import whisper

        _model_cache[MODEL_SIZE] = whisper.load_model(MODEL_SIZE)
    return _model_cache[MODEL_SIZE]


def transcribe(media_path: str) -> List[Dict[str, float | str]]:
    """
    Transcribe a media file (any format ffmpeg can read) into segments:
        [{"start": 14.22, "end": 17.10, "text": "..."}, ...]
    """
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
