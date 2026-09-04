"""
Unit tests for Stage 1 transcription (backend/pipeline/transcribe.py).

These tests NEVER load the real Whisper model or touch media files. The
`whisper` module is monkeypatched with a fake that returns shaped segment
dicts, so we can verify the lazy-load cache, the model-size selection, and
the segment normalisation (float timestamps + stripped text) with zero weight
download and zero quota.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import backend.pipeline.transcribe as tr  # noqa: E402


def _describe(model):
    return model["size"]


class _FakeResult(dict):
    """Mimics whisper's transcribe() return dict: `result["segments"]`."""

    def __init__(self, segments):
        super().__init__(segments=segments)


class _FakeModel:
    """Mimics whisper's load_model() return value: an object with the
    attributes the module actually uses (`.transcribe`, `.calls`, `.size`)."""

    def __init__(self, size):
        self.size = size
        self.calls = 0

    def transcribe(self, media_path, verbose=False):
        self.calls += 1
        return _FakeResult([
            {"start": 1.0, "end": 4.0, "text": "  hello world  "},
            {"start": 4.0, "end": 9.5, "text": "second segment  "},
        ])


def _fake_load_model_for(installed_sizes=None):
    installed_sizes = installed_sizes or {"base"}

    def fake_load_model(size):
        return _FakeModel(size)

    return fake_load_model


@pytest.fixture(autouse=True)
def _reset_model_cache():
    tr._model_cache.clear()
    yield
    tr._model_cache.clear()


def test_get_model_loads_and_caches_same_instance(monkeypatch):
    loaded = []

    def fake_load_model(size):
        m = _FakeModel(size)
        loaded.append(m)
        return m

    monkeypatch.setattr("whisper.load_model", fake_load_model)

    m1 = tr._get_model()
    m2 = tr._get_model()

    assert m1 is m2
    assert len(loaded) == 1  # second call served from cache


def test_get_model_respects_model_size_env(monkeypatch):
    loaded = []

    def fake_load_model(size):
        m = _FakeModel(size)
        loaded.append(size)
        return m

    monkeypatch.setattr("whisper.load_model", fake_load_model)
    monkeypatch.setattr(tr, "MODEL_SIZE", "small")

    tr._get_model()
    assert loaded == ["small"]


def test_transcribe_returns_normalised_segments(monkeypatch):
    monkeypatch.setattr(
        "whisper.load_model", _fake_load_model_for({"base"})
    )

    segs = tr.transcribe("some/media.mp4")

    assert segs == [
        {"start": 1.0, "end": 4.0, "text": "hello world"},
        {"start": 4.0, "end": 9.5, "text": "second segment"},
    ]
    # floats asserted explicitly (start came back as float, not str/int)
    assert all(isinstance(s["start"], float) and isinstance(s["end"], float) for s in segs)


def test_transcribe_caches_model_across_calls(monkeypatch):
    fake = _fake_load_model_for({"base"})
    monkeypatch.setattr("whisper.load_model", fake)

    tr.transcribe("media1.mp4")
    tr.transcribe("media2.mp4")

    model = tr._model_cache[tr.MODEL_SIZE]
    assert model.calls == 2  # two transcribes, one model instance


def test_transcribe_passes_media_path_and_verbose_false(monkeypatch):
    seen = {}

    def fake_load_model(size):
        model = _FakeModel(size)

        def transcribe(media_path, verbose=False):
            seen["path"] = media_path
            seen["verbose"] = verbose
            return _FakeResult([])

        model.transcribe = transcribe
        return model

    monkeypatch.setattr("whisper.load_model", fake_load_model)

    tr.transcribe("/abs/path/lec.mp4")

    assert seen["path"] == "/abs/path/lec.mp4"
    assert seen["verbose"] is False
