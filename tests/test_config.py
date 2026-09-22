"""backend/config.py — the env surface, pinned.

One file documents every env key the runtime reads. These tests pin the
typed-getter behavior (parsing, stripping, invalid-value fallbacks) and ensure
the examples file doesn't drift from the real surface: every key config reads
must appear in .env.example so a deployment can find it.
"""

from pathlib import Path

import pytest

from backend.config import (
    get_bool,
    get_float,
    get_int,
    get_str,
)

REPO = Path(__file__).resolve().parents[1]

# Import-time keys, their default, and type.
IMPORT_TIME_KEYS = {
    "LECGAP_DATABASE_URL": None,
    "LECGAP_MAX_UPLOAD_MB": 2048,
    "LECGAP_MAX_PIPELINE_JOBS": 3,
    "LECGAP_GROQ_MODEL": "openai/gpt-oss-20b",
    "LECGAP_OLLAMA_MODEL": "llama3.2",
    "LECGAP_OLLAMA_URL": "http://127.0.0.1:11434",
    "LECGAP_LLM_RETRIES": 2,
    "LECGAP_LLM_SLEEP_CAP_S": 120.0,
    "LECGAP_LLM_CACHE_TTL_S": 30 * 24 * 3600,
    "LECGAP_EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2",
    "LECGAP_STRUCTURE_WINDOW_CHARS": 8000,
    "LECGAP_STRUCTURE_OVERLAP_FRAC": 0.25,
    "LECGAP_STRUCTURE_MAX_TOKENS": 3000,
    "WHISPER_BACKEND": "local",
    "WHISPER_MODEL": "base",
    "GROQ_WHISPER_MODEL": "whisper-large-v3-turbo",
    "GROQ_WHISPER_UPLOAD_LIMIT": 24 * 1024 * 1024,
    "GROQ_WHISPER_MAX_CHUNK_S": 300,
    "LECGAP_WHISPER_RETRIES": 2,
    "LECGAP_WHISPER_500_BACKOFF": 5.0,
}

# Lazy (call-time) keys plus the auth keys.
LAZY_KEYS = {
    "LECGAP_API_KEY",
    "GROQ_API_KEY",
    "LECGAP_LLM_REASONING",
    "LECGAP_SNAP_SILENCE",
    "LECGAP_CLIP_STREAMCOPY",
    "LECGAP_CLIP_REENCODE_THRESHOLD_S",
    "LECGAP_CLIP_WORKERS",
    "WHISPER_BACKEND",  # both import-time (constant) and read lazily for override
}


# ------------------------------------------------------------ typed getters

def test_get_int_default_and_invalid_fallback(monkeypatch):
    name = "LECGAP_MAX_UPLOAD_MB"
    monkeypatch.delenv(name, raising=False)
    assert get_int(name, 2048) == 2048
    monkeypatch.setenv(name, "0")
    assert get_int(name, 2048) == 0
    monkeypatch.setenv(name, "not-a-number")
    assert get_int(name, 2048) == 2048


def test_get_float_parses_and_falls_back(monkeypatch):
    name = "LECGAP_LLM_SLEEP_CAP_S"
    monkeypatch.delenv(name, raising=False)
    assert get_float(name, 120.0) == 120.0
    monkeypatch.setenv(name, "7.5")
    assert get_float(name, 120.0) == 7.5
    monkeypatch.setenv(name, "x")
    assert get_float(name, 120.0) == 120.0


def test_get_str_strips_values_and_returns_default(monkeypatch):
    name = "LECGAP_GROQ_MODEL"
    monkeypatch.delenv(name, raising=False)
    assert get_str(name, "default-model") == "default-model"
    monkeypatch.setenv(name, "  llama-3.1-8b  ")
    assert get_str(name, "default-model") == "llama-3.1-8b"
    monkeypatch.setenv(name, "   ")
    assert get_str(name, "default-model") == ""


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("yes", True), ("TRUE", True),
    ("0", False), ("false", False), ("no", False), ("", False), ("2", False),
])
def test_get_bool_parses_truthy_and_falsy(monkeypatch, raw, expected):
    name = "LECGAP_LLM_REASONING"
    monkeypatch.setenv(name, raw)
    assert get_bool(name) is expected


# -------------------------------------------------------------- lazy helpers

def test_api_key_strips(monkeypatch):
    monkeypatch.setenv("LECGAP_API_KEY", "  secret-key  ")
    from backend.config import api_key
    assert api_key() == "secret-key"


def test_groq_api_key_strips_and_defaults_empty(monkeypatch):
    from backend.config import groq_api_key
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert groq_api_key() == ""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert groq_api_key() == "k"


def test_clip_workers_validates(monkeypatch):
    from backend.config import clip_workers
    monkeypatch.delenv("LECGAP_CLIP_WORKERS", raising=False)
    assert clip_workers() is None
    monkeypatch.setenv("LECGAP_CLIP_WORKERS", "12")
    assert clip_workers() == 12
    monkeypatch.setenv("LECGAP_CLIP_WORKERS", "0")  # clamped to 1
    assert clip_workers() == 1
    monkeypatch.setenv("LECGAP_CLIP_WORKERS", "auto")
    assert clip_workers() is None


def test_clip_reencode_threshold_defaults_on_junk(monkeypatch):
    from backend.config import clip_reencode_threshold_s
    monkeypatch.delenv("LECGAP_CLIP_REENCODE_THRESHOLD_S", raising=False)
    assert clip_reencode_threshold_s() == 120.0
    monkeypatch.setenv("LECGAP_CLIP_REENCODE_THRESHOLD_S", "60")
    assert clip_reencode_threshold_s() == 60.0
    monkeypatch.setenv("LECGAP_CLIP_REENCODE_THRESHOLD_S", "boom")
    assert clip_reencode_threshold_s() == 120.0


def test_whisper_backend_override_distinguishes_unset_from_value(monkeypatch):
    from backend.config import whisper_backend_override
    monkeypatch.delenv("WHISPER_BACKEND", raising=False)
    assert whisper_backend_override() == ""
    monkeypatch.setenv("WHISPER_BACKEND", "groq")
    assert whisper_backend_override() == "groq"


# ------------------------------------------------------------- surface audit

def test_env_example_documents_every_import_time_key():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    missing = [k for k in IMPORT_TIME_KEYS if k not in text]
    assert missing == []


def test_env_example_documents_every_lazy_key():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    missing = [k for k in sorted(LAZY_KEYS) if k not in text]
    assert missing == []