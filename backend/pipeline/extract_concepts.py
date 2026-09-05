"""
Stage 2 — Concept Extraction (spoken track)
See plan/ARCHITECTURE.md, Stage 2.

Two independent tracks feed one combined concept list:

  extract_spoken_concepts(transcript)  -> LLM reads transcript chunks and
                                          pulls out explicit + implicit
                                          concepts, each with a rough
                                          timestamp range.

  merge_concepts(lists)                -> embedding-similarity dedup so
                                          near-duplicate names from different
                                          chunks collapse into one node.

  extract_visual_concepts(video_path)  -> Phase 2b (CLIP + OCR), stub for now
                                          (see plan/ROADMAP.md — cuttable).

Chunking is quota-aware: concepts are extracted per transcript chunk so a
lecture course stays inside the per-minute token window, and every LLM call is
cached for repeat-free (zero-cost) re-runs during development.
"""

import json
import re
from typing import Dict, List

from backend.pipeline.llm import complete

# ~12K chars ≈ ~3K tokens per chunk (plus <500 output each) — well inside
# the Developer-plan 8K tokens/min window even during a burst of extractions.
MAX_CHARS_PER_CHUNK = int(12000)

SYSTEM_PROMPT = (
    "You analyze a lecture transcript segment and identify the academic "
    f"concepts being taught. Reply with JSON only: "
    f'{{"concepts":[{{"name":"...","implicit":true|false}}, ...]}}. '
    "Rules: (1) each entry is one concept; (2) include concepts that are "
    "implicitly referenced even if never named aloud; (3) return ONLY the JSON; "
    "no markdown, no commentary."
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
        name = str(c.get("name", "")).strip()
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
            chunk["text"],
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


# Phase 2b — visual track (CLIP + OCR). Deliberately a stub: the system is
# fully functional with the spoken track alone; visual adds slide-only
# concepts. Scheduled per plan/ROADMAP.md.
def extract_visual_concepts(video_path: str) -> List[Dict]:
    raise NotImplementedError("Phase 2b — visual concept extraction not yet implemented")


def merge_concepts(
    lists: List[List[Dict]],
    *,
    threshold: float = 0.85,
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> List[Dict]:
    """
    Merge concept lists, collapsing near-duplicate names into one entry
    via embedding similarity. Returns the deduplicated combined list.

    `lists` is a list of concept lists (e.g. [spoken, visual]). Grouping
    strategy: concepts are compared greedily per name-similarity against a
    running list of representatives.
    """
    merged: List[Dict] = []
    reps: List[str] = []
    embs: List = []

    from sentence_transformers import SentenceTransformer, util

    model = SentenceTransformer(embedding_model)

    for lst in lists:
        for c in lst:
            if not c.get("name"):
                continue
            vec = model.encode([c["name"]], convert_to_tensor=False)[0]
            best_sim = 0.0
            if embs:
                best_sim = float(util.cos_sim([vec], embs).max())
            if best_sim >= threshold:
                continue
            merged.append(dict(c))
            reps.append(c["name"])
            embs.append(vec)
    return merged
