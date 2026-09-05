"""
LLM access layer — foundation for Phase 2 (concept extraction).

Backend priority order:

    1. SQLite cache      identical prompt never re-calls any API (zero cost)
    2. Groq API          fast; shared Developer-plan quota (live-verified:
                         30 req + 8K tokens/min, 1K req + 200K tokens/day
                         for gpt-oss-20b), protected by the cache and
                         rate-limit-aware backoff on HTTP 429
    3. Ollama (local)    final fallback — unlimited but requires a local
                         install; most machines won't have it, so it is
                         strictly last resort

Every call goes through complete(); callers receive an LLMResult describing
where the answer came from and what it cost.
"""

import hashlib
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

from backend.models.db import LLMCache, SessionLocal

GROQ_MODEL = os.getenv("LECGAP_GROQ_MODEL", "openai/gpt-oss-20b")
OLLAMA_MODEL = os.getenv("LECGAP_OLLAMA_MODEL", "llama3.2")
OLLAMA_BASE_URL = os.getenv("LECGAP_OLLAMA_URL", "http://127.0.0.1:11434")
MAX_RETRIES = int(os.getenv("LECGAP_LLM_RETRIES", "2"))
SLEEP_CAP_S = 120.0


@dataclass
class LLMResult:
    text: str
    backend: str
    model: str
    cached: bool
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


def _parse_reset_seconds(raw: str) -> float:
    """Parse Groq reset strings like '644ms', '1m26.4s', '2h3m45s'."""
    total = 0.0
    for num, unit in re.findall(r"([0-9.]+)\s*(ms|s|m|h)", raw or ""):
        total += float(num or 0) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def _cache_key(model: str, system: str, user: str, max_tokens: int, temperature: float) -> str:
    payload = f"{model}|{max_tokens}|{temperature}|{system}|{user}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[LLMCache]:
    with SessionLocal() as db:
        row = db.get(LLMCache, key)
        if row is not None:
            db.expunge(row)
        return row


def _cache_put(key: str, result: LLMResult) -> None:
    with SessionLocal() as db:
        db.merge(
            LLMCache(
                key=key,
                backend=result.backend,
                model=result.model,
                response_text=result.text,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
        )
        db.commit()


def _call_groq(system: str, user: str, max_tokens: int, temperature: float) -> LLMResult:
    from groq import Groq, RateLimitError

    client = Groq()
    kwargs = dict(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if GROQ_MODEL.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = "low"

    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(model=GROQ_MODEL, **kwargs)
            return LLMResult(
                text=(resp.choices[0].message.content or "").strip(),
                backend="groq",
                model=resp.model,
                cached=False,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
            )
        except RateLimitError as exc:
            last_error = exc
            reset = 60.0
            try:
                reset = _parse_reset_seconds(
                    exc.response.headers.get("x-ratelimit-reset-requests", "60s")
                )
            except Exception:
                pass
            if attempt == MAX_RETRIES or reset > SLEEP_CAP_S:
                raise RuntimeError(
                    f"Groq rate limit exhausted (window resets in {reset:.0f}s). "
                    "Serve from cache or wait."
                ) from exc
            time.sleep(min(reset, SLEEP_CAP_S))
        except Exception as exc:
            raise RuntimeError(f"Groq call failed: {type(exc).__name__}: {exc}") from exc
    raise RuntimeError(f"Groq call failed after retries: {last_error}")


def _ollama_reachable() -> bool:
    try:
        return (
            requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=1.5).status_code == 200
        )
    except requests.RequestException:
        return False


def _call_ollama(system: str, user: str, max_tokens: int, temperature: float) -> LLMResult:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": temperature},
        },
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    return LLMResult(
        text=(data.get("message", {}).get("content") or "").strip(),
        backend="ollama",
        model=data.get("model", OLLAMA_MODEL),
        cached=False,
        prompt_tokens=data.get("prompt_eval_count"),
        completion_tokens=data.get("eval_count"),
    )


def complete(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 1000,
    temperature: float = 0.0,
) -> LLMResult:
    """Cached, quota-aware completion. See module docstring for priority order."""
    resolved_model = model or GROQ_MODEL
    key = _cache_key(resolved_model, system, user, max_tokens, temperature)

    hit = _cache_get(key)
    if hit is not None:
        return LLMResult(
            text=hit.response_text,
            backend=hit.backend,
            model=hit.model,
            cached=True,
            prompt_tokens=hit.prompt_tokens,
            completion_tokens=hit.completion_tokens,
        )

    errors = []
    for name, caller in (("groq", lambda: _call_groq(system, user, max_tokens, temperature)),
                         ("ollama", lambda: _call_ollama(system, user, max_tokens, temperature))):
        if name == "groq" and not os.getenv("GROQ_API_KEY"):
            continue
        if name == "ollama" and not _ollama_reachable():
            errors.append("ollama: not reachable")
            continue
        try:
            result = caller()
            _cache_put(key, result)
            return result
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    raise RuntimeError(
        "No LLM backend succeeded. " + ("; ".join(errors) if errors else "none configured")
    )


def backend_status() -> dict:
    """Cheap availability probe for /health and the frontend."""
    return {
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "ollama_reachable": _ollama_reachable(),
        "groq_model": GROQ_MODEL,
        "ollama_model": OLLAMA_MODEL,
    }
