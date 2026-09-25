"""In-process API usage store — Groq rate-limit transparency.

Captures Groq rate-limit headers on every LLM / Whisper call, split per service
(``groq.chat`` vs ``groq.whisper``), so the student dashboard can show how much
transcribing is left before the quota window resets (plan 10 / contract §usage).

Everything stays in memory; a process restart clears it and the values
self-heal on the next API call. Nothing secret leaves the backend — GET /usage
(guarded) serves only aggregates.
"""

import threading
import time

_lock = threading.Lock()
_state = {
    "groq.chat": {},
    "groq.whisper": {},
}
_total_calls = {"groq.chat": 0, "groq.whisper": 0}

_INT_HEADERS = (
    "limit_requests",
    "remaining_requests",
    "limit_tokens",
    "remaining_tokens",
)


def _hdr(headers, name, default=None):
    if headers is None:
        return default
    value = headers.get(f"x-ratelimit-{name.replace('_', '-')}")
    if value is None:
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def parse_reset_seconds(value) -> float:
    """Parse Groq reset headers like '7m18.5s', '60s', '48.5s' -> seconds."""
    if not value:
        return None
    text = str(value).strip().lower()
    total = 0.0
    num = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            num += ch
        elif num:
            factor = {"h": 3600.0, "m": 60.0, "s": 1.0}.get(ch)
            if factor is not None:
                total += float(num) * factor
            num = ""
    return total if total else None


def record_groq(service: str, model: str, headers=None) -> None:
    """Record rate-limit headers from one Groq response (or a 429 fallback)."""
    global _total_calls
    with _lock:
        _total_calls[service] += 1
        entry = _state.setdefault(service, {})
        if model:
            entry["model"] = model
        entry["last_checked"] = time.time()
        for key in _INT_HEADERS:
            value = _hdr(headers, key)
            if value is not None:
                entry[key] = value
        reset = _hdr(headers, "reset_requests")
        if reset is None:
            reset = headers.get("x-ratelimit-reset-requests") if headers else None
        parsed = parse_reset_seconds(reset)
        if parsed is not None:
            entry["reset_in_s"] = round(parsed, 1)


def snapshot(groq_model=None, whisper_model=None,
             local_available=None, ffmpeg_ok=None, ollama_reachable=None) -> dict:
    """Snapshot for GET /usage. Values that were never seen stay absent so the
    frontend can say 'no usage data yet' instead of showing fake zeros."""
    with _lock:
        groq_chat = dict(_state.get("groq.chat", {}))
        groq_whisper = dict(_state.get("groq.whisper", {}))
        chat_calls = _total_calls["groq.chat"]
        whisper_calls = _total_calls["groq.whisper"]
    groq_chat.setdefault("model", groq_model)
    groq_whisper.setdefault("model", whisper_model)
    return {
        "services": {
            "groq.chat": {"calls": chat_calls, **groq_chat},
            "groq.whisper": {"calls": whisper_calls, **groq_whisper},
            "local": {
                "available": bool(local_available),
                "unlimited": True,
                "ffmpeg_ok": bool(ffmpeg_ok),
            },
            "ollama": {"reachable": bool(ollama_reachable)},
        },
    }