"""
Stage 5 — Clip Segmentation
See plan/ARCHITECTURE.md, Stage 5.

Cuts one clip per concept per timestamp range using FFmpeg. Pure
infrastructure.

  cut_clip(media_path, start, end, out_path) -> ffmpeg subprocess call.
"""

# TODO (Phase 5): shell out to ffmpeg (or use ffmpeg-python) to cut clips
# into data/processed/clips/<lecture_id>/<concept_id>.mp4
