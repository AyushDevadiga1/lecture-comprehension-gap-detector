"""
Stage 2 — Concept Extraction
See plan/ARCHITECTURE.md, Stage 2.

Two independent tracks that both feed into one combined concept list:

  extract_spoken_concepts(transcript)   -> LLM reads transcript chunks,
                                            pulls out explicit + implicit
                                            concepts.

  extract_visual_concepts(video_path)   -> samples frames at scene changes,
                                            runs CLIP (frame-to-text match)
                                            + OCR (on-screen text/equations).

  merge_concepts(spoken, visual)        -> combines both into one
                                            deduplicated list per lecture.
"""

# TODO (Phase 2): implement extract_spoken_concepts — LLM call (Groq/Ollama),
# prompted to return concepts as structured JSON.

# TODO (Phase 2b): implement extract_visual_concepts — CLIP (zero-shot,
# HuggingFace) + pytesseract OCR, sampling frames on scene change only
# (not every frame — see plan/ARCHITECTURE.md for why).

# TODO: merge_concepts — embedding-similarity dedup so near-duplicate
# concepts ("Gradient Descent" / "GD optimization") collapse into one.
