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
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional

import requests
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.models.db import LLMCache, SessionLocal

from backend.config import (
    GROQ_MODEL,
    LLM_CACHE_TTL_S,
    LLM_MAX_RETRIES as MAX_RETRIES,
    LLM_SLEEP_CAP_S as SLEEP_CAP_S,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    groq_api_key,
)

# Cached completions may embed lecture content (potentially student-identifying
# in refine runs), so rows expire after this many seconds (default 30 days).


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


def _from_cache(hit: LLMCache) -> LLMResult:
    return LLMResult(
        text=hit.response_text,
        backend=hit.backend,
        model=hit.model,
        cached=True,
        prompt_tokens=hit.prompt_tokens,
        completion_tokens=hit.completion_tokens,
    )


def _cache_age_s(row: LLMCache) -> Optional[float]:
    """Seconds since the row was written (None when it has no timestamp).

    SQLite returns naive datetimes even for timezone-aware columns, so both
    sides are normalised to naive UTC before subtracting.
    """
    then = row.created_at
    if then is None:
        return None
    if then.tzinfo is not None:
        then = then.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (now - then).total_seconds()


def _cache_get(key: str) -> Optional[LLMCache]:
    with SessionLocal() as db:
        row = db.get(LLMCache, key)
        if row is None:
            return None
        # Expire stale rows instead of replaying (possibly sensitive) content
        # forever (SECURITY_AUDIT #16).
        age = _cache_age_s(row)
        if age is not None and age > LLM_CACHE_TTL_S:
            db.delete(row)
            db.commit()
            return None
        db.expunge(row)
        return row


def _cache_put(key: str, result: LLMResult) -> None:
    if not result.text or not result.text.strip():
        # never persist an empty completion: it would poison the cache and
        # every later run would replay the dead answer instead of retrying.
        return
    with SessionLocal() as db:
        db.execute(
            sqlite_insert(LLMCache)
            .values(
                key=key,
                backend=result.backend,
                model=result.model,
                response_text=result.text,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            .on_conflict_do_nothing()
        )
        db.commit()


def _cache_del(key: str) -> None:
    """Drop a cached row (used to purge poisoned empty completions)."""
    with SessionLocal() as db:
        row = db.get(LLMCache, key)
        if row is not None:
            db.delete(row)
            db.commit()


class _KeyLockMap:
    """Reference-counted per-key locks for single-flight completion.

    Threads that MISS the same cache key serialize on one per-key lock so a
    single backend call + cache insert serves them all (no double API billing
    for identical prompts, no duplicate-PK insert race). Entries are dropped
    when the last holder releases, so the map stays bounded over a long-lived
    process.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    @contextmanager
    def __call__(self, key: str) -> Iterator[None]:
        with self._guard:
            lock, n = self._locks.get(key, (None, 0))
            if lock is None:
                lock = threading.Lock()
            self._locks[key] = (lock, n + 1)
        lock.acquire()
        try:
            yield
        finally:
            with self._guard:
                lock, n = self._locks[key]
                n -= 1
                if n <= 0:
                    del self._locks[key]
                else:
                    self._locks[key] = (lock, n)
            lock.release()


_inflight = _KeyLockMap()


def _call_groq(system: str, user: str, max_tokens: int, temperature: float) -> LLMResult:
    from groq import Groq, RateLimitError

    # lazy: usage.py is imported by the routes package which itself imports this
    # module — a top-level import would form a cycle (backend.api <-> llm).
    from backend.api import usage

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
            raw = client.chat.completions.with_raw_response.create(model=GROQ_MODEL,
                                                                   **kwargs)
            try:
                usage.record_groq("groq.chat", GROQ_MODEL, raw.headers)
            except Exception:  # noqa: BLE001 - usage capture must never break a call
                pass
            resp = raw.parse()
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
            try:
                usage.record_groq(
                    "groq.chat", GROQ_MODEL,
                    getattr(exc.response, "headers", None),
                )
            except Exception:  # noqa: BLE001
                pass
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
    """Cached, quota-aware completion. See module docstring for priority order.

    Concurrent threads that miss the same key are serialized by a per-key
    single-flight lock: the winner makes the backend calls and fills the cache,
    the waiters re-read the cache and reuse the result. Distinct prompts keep
    their parallelism, so the 6-worker MCQ pool stays concurrent.
    """
    resolved_model = model or GROQ_MODEL
    key = _cache_key(resolved_model, system, user, max_tokens, temperature)

    hit = _cache_get(key)
    if hit is not None:
        if hit.response_text and hit.response_text.strip():
            return _from_cache(hit)
        # poisoned cache row (empty completion) — drop and regenerate live
        _cache_del(key)

    with _inflight(key):
        hit = _cache_get(key)
        if hit is not None:
            if hit.response_text and hit.response_text.strip():
                return _from_cache(hit)
            _cache_del(key)

        errors = []
        for attempt in range(3):  # a backend can return an empty completion; retry
            for name, caller in (("groq", lambda: _call_groq(system, user, max_tokens, temperature)),
                                 ("ollama", lambda: _call_ollama(system, user, max_tokens, temperature))):
                if name == "groq" and not groq_api_key():
                    continue
                if name == "ollama" and not _ollama_reachable():
                    errors.append("ollama: not reachable")
                    continue
                try:
                    result = caller()
                    if not result.text or not result.text.strip():
                        errors.append(f"{name}: empty completion")
                        continue
                    _cache_put(key, result)
                    return result
                except Exception as exc:
                    errors.append(f"{name}: {exc}")

    raise RuntimeError(
        "No LLM backend succeeded. " + ("; ".join(errors) if errors else "none configured")
    )


def backend_status_detailed() -> dict:
    """Detailed availability probe — internal/admin use only.

    Discloses which providers/models are configured, so it must not be served
    from the public /health endpoint (SECURITY_AUDIT #15).
    """
    return {
        "groq_configured": bool(groq_api_key()),
        "ollama_reachable": _ollama_reachable(),
        "groq_model": GROQ_MODEL,
        "ollama_model": OLLAMA_MODEL,
    }


def backend_status() -> dict:
    """Public, sanitized availability probe for /health.

    Reports only whether some LLM backend is usable right now; it never leaks
    provider names, model names, or whether a particular secret is set.
    """
    detailed = backend_status_detailed()
    return {
        "any_backend_available": bool(
            detailed["groq_configured"] or detailed["ollama_reachable"]
        )
    }
