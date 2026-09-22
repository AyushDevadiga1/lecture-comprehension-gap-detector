"""
Stage 2 — Concept Extraction (spoken track)
See plan/ARCHITECTURE.md, Stage 2.

  extract_spoken_concepts(transcript)  -> LLM reads transcript chunks and
                                          pulls out explicit + implicit
                                          concepts, each with a rough
                                          timestamp range.

Chunking is quota-aware: concepts are extracted per transcript chunk so a
lecture course stays inside the per-minute token window, and every LLM call is
cached for repeat-free (zero-cost) re-runs during development.

Near-duplicate names across chunks collapse in ConceptGraph.add_concepts
(Stage 4), not here. The Phase 2b visual track (CLIP + OCR) is cuttable per
plan/ROADMAP.md.
"""

import json
import re
from typing import Dict, List

from backend.pipeline.llm import complete
from backend.pipeline.prompt_guard import DATA_GUARD, delimit_untrusted

# ~12K chars ≈ ~3K tokens per chunk (plus <500 output each) — well inside
# the Developer-plan 8K tokens/min window even during a burst of extractions.
MAX_CHARS_PER_CHUNK = int(12000)
# LLM-derived concept names are untrusted: bound them before they reach the
# DB/UI (SECURITY_AUDIT #17).
MAX_NAME_CHARS = 120

SYSTEM_PROMPT = (
    "You analyze a lecture transcript segment and identify the academic "
    f"concepts being taught. Reply with JSON only: "
    f'{{"concepts":[{{"name":"...","implicit":true|false}}, ...]}}. '
    "Rules: (1) each entry is one concept; (2) include concepts that are "
    "implicitly referenced even if never named aloud; (3) return ONLY the JSON; "
    "no markdown, no commentary. " + DATA_GUARD
)


def _strip_code_fence(text: str) -> str:
    """Groq sometimes wraps JSON in ```json ... ``` fences — strip them."""
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def _parse_concepts(text: str) -> List[Dict]:
    text = _strip_code_fence(text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"LLM returned non-JSON for concept extraction: {text[:200]!r}")
        data = json.loads(text[start : end + 1])

    concepts = data.get("concepts", [])
    out: List[Dict] = []
    for c in concepts:
        name = str(c.get("name", "")).strip()[:MAX_NAME_CHARS]
        if not name:
            continue
        out.append({"name": name, "implicit": bool(c.get("implicit", False))})
    return out


def _chunks(docs: List[Dict], max_chars: int) -> List[Dict[str, object]]:
    """Group transcript segments into ~max_chars chunks, each a dict
    {"start_s", "end_s", "text"} so downstream timestamping stays valid."""
    chunks: List[Dict[str, object]] = []
    buf: List[Dict] = []
    size = 0
    for seg in docs:
        seg_text = f"[{seg['start_s']:.1f}s] {seg['text']}\n"
        if buf and size + len(seg_text) > max_chars:
            chunks.append(
                {
                    "start_s": buf[0]["start_s"],
                    "end_s": buf[-1]["end_s"],
                    "text": "".join(f"[{s['start_s']:.1f}s] {s['text']}\n" for s in buf),
                }
            )
            buf, size = [], 0
        buf.append(seg)
        size += len(seg_text)
    if buf:
        chunks.append(
            {
                "start_s": buf[0]["start_s"],
                "end_s": buf[-1]["end_s"],
                "text": "".join(f"[{s['start_s']:.1f}s] {s['text']}\n" for s in buf),
            }
        )
    return chunks


def extract_spoken_concepts(docs: List[Dict]) -> List[Dict]:
    """
    Extract concepts from a transcript.

    `docs` is the list of transcript segments (each with start_s, end_s, text).
    Returns a list of:
        {"name": str, "source": "spoken", "implicit": bool,
         "start_s": float|None, "end_s": float|None}
    """
    if not docs:
        return []

    concepts: List[Dict] = []
    for chunk in _chunks(docs, MAX_CHARS_PER_CHUNK):
        result = complete(
            SYSTEM_PROMPT,
            delimit_untrusted(chunk["text"]),
            max_tokens=500,
            temperature=0.0,
        )
        parsed = _parse_concepts(result.text)
        for c in parsed:
            concepts.append(
                {
                    "name": c["name"],
                    "source": "spoken",
                    "implicit": c["implicit"],
                    "start_s": chunk["start_s"],
                    "end_s": chunk["end_s"],
                }
            )
    return concepts
