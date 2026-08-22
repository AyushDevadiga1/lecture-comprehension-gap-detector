"""
Stage 1 — Transcription
See plan/ARCHITECTURE.md, Stage 1.

Takes a raw lecture audio/video file and produces a timestamped
transcript using Whisper. Pure infrastructure — no ML claim lives here.

Planned interface:

    def transcribe(media_path: str) -> list[dict]:
        '''
        Returns a list of segments, each like:
            {"start": 14.22, "end": 17.10, "text": "..."}
        '''
"""

# TODO (Phase 1): load Whisper, run on media_path, return timestamped segments.
# Keep this function pure (no DB writes here) — persistence happens in
# backend/models/db.py, called from backend/api/routes.py.
