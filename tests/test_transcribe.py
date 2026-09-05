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


# --- Groq-backend (WHISPER_BACKEND=groq) coverage ---------------------------
# The Groq backend never runs during these tests: ffmpeg subprocesses, duration
# probes, and the Groq client are all monkeypatched, so nothing downloads, no
# audio is sent anywhere, and no quota is spent.

class _FakeSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class _FakeResp:
    def __init__(self, segments=None, text=""):
        self.segments = segments
        self.text = text


class _FakeTranscriptions:
    def __init__(self, resp):
        self.create = lambda **kwargs: resp


class _FakeAudio:
    def __init__(self, resp):
        self.transcriptions = _FakeTranscriptions(resp)


class _FakeGroqClient:
    def __init__(self, resp=None):
        self.audio = _FakeAudio(resp)


def test_backend_defaults_to_local():
    assert tr.BACKEND == "local"


def test_transcribe_dispatches_to_groq_backend(monkeypatch):
    calls = []

    def fake_groq(media_path):
        calls.append(media_path)
        return ["segments-from-groq"]

    monkeypatch.setattr(tr, "BACKEND", "groq")
    monkeypatch.setattr(tr, "_transcribe_groq", fake_groq)

    out = tr.transcribe("media.mp4")
    assert calls == ["media.mp4"]
    assert out == ["segments-from-groq"]


def test_groq_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        tr._transcribe_groq("media.mp4")


def test_groq_requires_ffmpeg(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(tr, "_ffmpeg_available", lambda: False)

    with pytest.raises(RuntimeError, match="ffmpeg"):
        tr._transcribe_groq("media.mp4")


def test_groq_single_call_when_file_fits(monkeypatch):
    """No chunking: downmix -> one transcribe call, file passed as-is."""
    fake_chunks = {"flac": "/tmp/audio.flac", "calls": []}

    def fake_downmix(src, dst):
        Path(dst).write_bytes(b"flac-bytes")
        fake_chunks["flac"] = dst
        return dst

    def fake_transcribe_chunk(client, chunk, offset):
        fake_chunks["calls"].append((chunk, offset))
        return [{"start": 0.5 + offset, "end": 2.0 + offset, "text": "ok"}]

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(tr, "_ffmpeg_available", lambda: True)
    monkeypatch.setattr(tr, "_downmix_to_flac", fake_downmix)
    monkeypatch.setattr(tr, "_probe_duration", lambda _: 30.0)
    monkeypatch.setattr(tr, "_chunk_seconds", lambda *a, **k: 0)
    monkeypatch.setattr(tr, "_transcribe_chunk", fake_transcribe_chunk)
    monkeypatch.setattr("groq.Groq", _FakeGroqClient)

    out = tr._transcribe_groq("media.mp4")

    assert len(fake_chunks["calls"]) == 1
    assert fake_chunks["calls"][0][0].endswith(".flac")
    assert fake_chunks["calls"][0][1] == 0.0
    assert out == [{"start": 0.5, "end": 2.0, "text": "ok"}]


def test_groq_splits_and_offsets_oversized_files(monkeypatch):
    fake_calls = []

    def fake_downmix(src, dst):
        Path(dst).write_bytes(b"x" * 100)
        return dst

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(tr, "_ffmpeg_available", lambda: True)
    monkeypatch.setattr(tr, "_downmix_to_flac", fake_downmix)
    monkeypatch.setattr(tr, "_probe_duration", lambda _: 60.0)
    monkeypatch.setattr(tr, "_chunk_seconds", lambda *a, **k: 30)
    monkeypatch.setattr(
        tr, "_split_flac", lambda flac, d, s: [Path(d, "chunk_000.flac"), Path(d, "chunk_001.flac")]
    )

    def fake_transcribe_chunk(client, chunk, offset):
        fake_calls.append(offset)
        return [{"start": offset, "end": offset + 1.0, "text": f"c{offset:g}"}]

    monkeypatch.setattr(tr, "_transcribe_chunk", fake_transcribe_chunk)
    monkeypatch.setattr("groq.Groq", _FakeGroqClient)

    out = tr._transcribe_groq("media.mp4")

    assert fake_calls == [0.0, 30.0]
    assert out == [
        {"start": 0.0, "end": 1.0, "text": "c0"},
        {"start": 30.0, "end": 31.0, "text": "c30"},
    ]
    assert all(isinstance(s["start"], float) for s in out)


def test_groq_chunk_maps_segments_and_strips_text(tmp_path):
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    resp = _FakeResp(
        segments=[
            {"start": 1.0, "end": 3.0, "text": "  hello  "},
            {"start": 3.0, "end": 5.5, "text": "groq transcribe  "},
        ]
    )

    client = _FakeGroqClient(resp)
    created = {}

    original_create = client.audio.transcriptions.create

    def spy_create(**kwargs):
        created.update(kwargs)
        return original_create(**kwargs)

    client.audio.transcriptions.create = spy_create

    out = tr._transcribe_chunk(client, str(chunk), offset=100.0)

    assert created["response_format"] == "verbose_json"
    assert created["timestamp_granularities"] == ["segment"]
    assert created["file"][0] == "chunk_000.flac"
    assert out == [
        {"start": 101.0, "end": 103.0, "text": "hello"},
        {"start": 103.0, "end": 105.5, "text": "groq transcribe"},
    ]
    assert all(isinstance(s["start"], float) and isinstance(s["end"], float) for s in out)


def test_groq_chunk_handles_attribute_style_segments(tmp_path):
    """Some SDK shapes expose segments as objects, not dicts — both must work."""
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    resp = _FakeResp(segments=[_FakeSegment(1.0, 3.0, "obj style  ")])

    out = tr._transcribe_chunk(_FakeGroqClient(resp), str(chunk), offset=10.0)

    assert out == [{"start": 11.0, "end": 13.0, "text": "obj style"}]


def test_groq_chunk_falls_back_to_text_when_no_segments(monkeypatch, tmp_path):
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    client = _FakeGroqClient(_FakeResp(segments=None, text="single blob  "))
    monkeypatch.setattr(tr, "_probe_duration", lambda _: 12.5)

    out = tr._transcribe_chunk(client, str(chunk), offset=30.0)

    assert out == [{"start": 30.0, "end": 42.5, "text": "single blob"}]


def test_chunk_seconds_math():
    limit = 24 * 1024 * 1024
    assert tr._chunk_seconds(60.0, 5_000_000, limit) == 0  # fits -> no split
    # 300 MB over 100 s -> ~2.5 MB/s; want is ~6 s but the min_s floor keeps
    # call counts sane -> 20 s chunks (still far under the upload limit)
    assert tr._chunk_seconds(100.0, 300_000_000, limit) == 20
    # 1.2 GB over 1 h -> ~60 s chunks, a comfortable mid-range split
    assert tr._chunk_seconds(3600.0, 1_200_000_000, limit) == 60
    # 100 MB over 2 h w/ mono speech audio is sparse -> capped by max_s
    assert tr._chunk_seconds(7200.0, 100_000_000, limit) == 900
