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

    segs = tr.transcribe("some/media.mp4", backend="local")

    assert segs == [
        {"start": 1.0, "end": 4.0, "text": "hello world"},
        {"start": 4.0, "end": 9.5, "text": "second segment"},
    ]
    # floats asserted explicitly (start came back as float, not str/int)
    assert all(isinstance(s["start"], float) and isinstance(s["end"], float) for s in segs)


def test_transcribe_caches_model_across_calls(monkeypatch):
    fake = _fake_load_model_for({"base"})
    monkeypatch.setattr("whisper.load_model", fake)

    tr.transcribe("media1.mp4", backend="local")
    tr.transcribe("media2.mp4", backend="local")

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

    tr.transcribe("/abs/path/lec.mp4", backend="local")

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

    def fake_groq(media_path, progress_callback=None):
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
        tr, "_split_flac",
        lambda flac, d, s, duration=None: [(Path(d, "chunk_000.flac"), 0.0), (Path(d, "chunk_001.flac"), 30.0)]
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


def test_split_flac_reencodes_each_chunk(monkeypatch, tmp_path):
    flac = tmp_path / "audio.flac"
    flac.write_bytes(b"f")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"chunk")
        return tr.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)

    chunks = tr._split_flac(str(flac), str(tmp_path), 300, duration=650.0)

    assert [Path(c[0]).name for c in chunks] == [
        "chunk_000.flac",
        "chunk_001.flac",
        "chunk_002.flac",
    ]
    assert [c[1] for c in chunks] == [0.0, 300.0, 600.0]  # real start offsets
    assert len(calls) == 3
    for cmd in calls:
        assert "-f" not in cmd and "segment" not in cmd  # not a `-f segment` cut
        assert "-ss" in cmd and "-t" in cmd
    assert calls[-1][calls[-1].index("-t") + 1] == "50.000"  # tail remainder, 650 - 600


def _fake_run_with_stderr(stderr_text, returncode=0):
    def fake_run(cmd, **kwargs):
        return tr.subprocess.CompletedProcess(cmd, returncode, "", stderr_text)

    return fake_run


def test_detect_silence_offset_snaps_to_detected_pause(monkeypatch):
    monkeypatch.setattr(
        tr.subprocess, "run",
        _fake_run_with_stderr("silence_start: 2.500\nsilence_end: 2.9 | silence_duration: 0.4"),
    )
    assert tr._detect_silence_offset("audio.flac", target_s=300.0) == 299.5  # 297.0 + 2.5


def test_detect_silence_offset_returns_target_when_no_silence(monkeypatch):
    monkeypatch.setattr(tr.subprocess, "run", _fake_run_with_stderr(""))
    assert tr._detect_silence_offset("audio.flac", target_s=300.0) == 300.0


def test_detect_silence_offset_returns_target_on_ffmpeg_error(monkeypatch):
    monkeypatch.setattr(tr.subprocess, "run", _fake_run_with_stderr("boom", returncode=1))
    assert tr._detect_silence_offset("audio.flac", target_s=300.0) == 300.0


def test_detect_silence_offset_ignores_silence_outside_window(monkeypatch):
    # silence is 8s away from the ±3s window -> treated as no usable boundary
    monkeypatch.setattr(
        tr.subprocess, "run",
        _fake_run_with_stderr("silence_start: 8.000\nsilence_end: 8.5 | silence_duration: 0.5"),
    )
    assert tr._detect_silence_offset("audio.flac", target_s=300.0, window_s=3.0) == 300.0


def test_split_flac_snap_silence_moves_boundaries_and_tracks_offsets(monkeypatch, tmp_path):
    flac = tmp_path / "audio.flac"
    flac.write_bytes(b"f")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"chunk")
        return tr.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    # snap each boundary 2.5s late (into the silence after the nominal end)
    monkeypatch.setattr(tr, "_detect_silence_offset", lambda path, t, window_s=3.0: t + 2.5)

    chunks = tr._split_flac(str(flac), str(tmp_path), 300, duration=650.0, snap_silence=True)

    assert [Path(c[0]).name for c in chunks] == [
        "chunk_000.flac", "chunk_001.flac", "chunk_002.flac",
    ]
    assert [c[1] for c in chunks] == [0.0, 302.5, 605.0]  # uniform assumption would be [0, 300, 600]
    # first chunk reaches 302.5, second chunk is 302.5 -> 605.0 (2.5s drift), last chunk tails
    assert calls[0][calls[0].index("-t") + 1] == "302.500"
    assert calls[1][calls[1].index("-t") + 1] == "302.500"
    assert calls[2][calls[2].index("-t") + 1] == "45.000"


def test_split_flac_snap_does_not_consult_silence_for_tiny_tail(monkeypatch, tmp_path):
    flac = tmp_path / "audio.flac"
    flac.write_bytes(b"f")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"chunk")
        return tr.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    calls = []
    monkeypatch.setattr(
        tr, "_detect_silence_offset",
        lambda path, t, window_s=3.0: calls.append(t) or t,
    )

    # 310s file, 300s chunks: the trailing 10s tail is below the 15s guard,
    # so snapping must never run (no wasted ffmpeg seek).
    tr._split_flac(str(flac), str(tmp_path), 300, duration=310.0, snap_silence=True)
    assert calls == []


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
    # explicit hard duration cap (Groq 500 resilience) overrides max_s default
    assert tr._chunk_seconds(7200.0, 100_000_000, limit, max_s=300) == 300
    assert tr._chunk_seconds(240.0, 5_000_000, limit, max_s=300) == 0  # fits, still no split


def _make_rate_limit_error(reset="500ms"):
    """Construct a real groq.RateLimitError backed by a genuine httpx 429
    response so the SDK's exception plumbing works exactly as in production."""
    import httpx

    import groq

    resp = httpx.Response(
        429,
        request=httpx.Request(
            "POST", "https://api.groq.com/openai/v1/audio/transcriptions"
        ),
        headers={"x-ratelimit-reset-requests": reset},
    )
    return groq.RateLimitError("rate limited", response=resp, body=None)


class _FlakyAudio:
    """Fakes `client.audio.transcriptions.create`, failing N times before OK."""

    def __init__(self, resp, failures=2, reset="500ms"):
        self.resp = resp
        self.failures = failures
        self.reset = reset
        self.attempts = 0
        self.transcriptions = self

    def create(self, **kwargs):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise _make_rate_limit_error(self.reset)
        return self.resp


def test_groq_chunk_retries_on_rate_limit_429(monkeypatch, tmp_path):
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    flaky = _FlakyAudio(_FakeResp(text="recovered  ", segments=None))
    client = type("C", (), {"audio": flaky})()
    sleeps = []
    monkeypatch.setattr(tr.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(tr, "_probe_duration", lambda _: 5.0)

    out = tr._transcribe_chunk(client, str(chunk), offset=0.0)

    assert flaky.attempts == 3  # 2 rate-limits, then success
    assert sleeps == [0.5, 0.5]  # each backed off by the reset window
    assert out == [{"start": 0.0, "end": 5.0, "text": "recovered"}]


def test_groq_chunk_rate_limit_exhaustion_raises(monkeypatch, tmp_path):
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    always = _FlakyAudio(None, failures=99, reset="3600s")
    client = type("C", (), {"audio": always})()
    sleeps = []
    monkeypatch.setattr(tr.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(RuntimeError, match="rate limit exhausted"):
        tr._transcribe_chunk(client, str(chunk), offset=0.0)

    assert always.attempts == 1  # long reset > SLEEP_CAP -> raise immediately
    assert sleeps == []


def _make_internal_server_error():
    """Real groq.InternalServerError backed by a genuine httpx 500 response."""
    import httpx

    import groq

    resp = httpx.Response(
        500,
        request=httpx.Request(
            "POST", "https://api.groq.com/openai/v1/audio/transcriptions"
        ),
    )
    return groq.InternalServerError("boom", response=resp, body=None)


class _Flaky500Audio:
    """Fakes `client.audio.transcriptions.create`, failing 2x with 500 then OK."""

    def __init__(self, resp, failures=2):
        self.resp = resp
        self.failures = failures
        self.attempts = 0
        self.transcriptions = self

    def create(self, **kwargs):
        self.attempts += 1
        if self.attempts <= self.failures:
            raise _make_internal_server_error()
        return self.resp


def test_groq_chunk_retries_on_transient_500(monkeypatch, tmp_path):
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    flaky = _Flaky500Audio(_FakeResp(text="recovered ", segments=None))
    client = type("C", (), {"audio": flaky})()
    sleeps = []
    monkeypatch.setattr(tr.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(tr, "_probe_duration", lambda _: 6.0)

    out = tr._transcribe_chunk(client, str(chunk), offset=2.0)

    assert flaky.attempts == 3  # 2x HTTP 500, then success
    assert sleeps == [tr.TRANSCRIBE_500_BACKOFF_S, tr.TRANSCRIBE_500_BACKOFF_S]
    assert out == [{"start": 2.0, "end": 8.0, "text": "recovered"}]


def test_groq_chunk_500_exhaustion_raises(monkeypatch, tmp_path):
    chunk = tmp_path / "chunk_000.flac"
    chunk.write_bytes(b"audio-bytes")

    always = _Flaky500Audio(None, failures=99)
    client = type("C", (), {"audio": always})()
    sleeps = []
    monkeypatch.setattr(tr.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(RuntimeError, match="HTTP 500 repeatedly"):
        tr._transcribe_chunk(client, str(chunk), offset=0.0)

    assert always.attempts == 3  # exhausted after the retry budget
    assert sleeps == [tr.TRANSCRIBE_500_BACKOFF_S] * 2  # last attempt raises, no sleep


def test_validate_media_path_rejects_flag_injection():
    """SECURITY_AUDIT #5: a path starting with '-' would be parsed as an
    ffmpeg flag and must be rejected."""
    with pytest.raises(ValueError):
        tr._validate_media_path("-i")
    with pytest.raises(ValueError):
        tr._validate_media_path("  -y")
    with pytest.raises(ValueError):
        tr._validate_media_path("")
    with pytest.raises(ValueError):
        tr._validate_media_path("a\x00b")


def test_validate_media_path_bounds_existing_files(tmp_path):
    """A real file outside the repo data/ tree is refused; paths inside (or
    non-existent stubs used by tests) pass through."""
    outside = tmp_path / "evil.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        tr._validate_media_path(str(outside))

    # non-existent relative/absolute stubs are allowed (unit-test paths)
    assert tr._validate_media_path("some/media.mp4") == "some/media.mp4"
    assert tr._validate_media_path("/abs/path/lec.mp4") == "/abs/path/lec.mp4"


def test_transcribe_rejects_unsafe_media_path():
    with pytest.raises(ValueError):
        tr.transcribe("--version", backend="local")
