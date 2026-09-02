"""
Tests for Stage 5 clip segmentation (backend/pipeline/segment_clips.py).

Pure logic only: ffmpeg subprocess calls are monkeypatched, so no binary, no
media files, no real cutting. Persistence rows are checked against an
in-memory SQLite engine.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _true_ffmpeg(monkeypatch, returncode=0):
    """Return a cut_clip function whose subprocess.run is faked"""
    import subprocess

    from backend.pipeline import segment_clips

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[:])
        return type("R", (), {"returncode": returncode, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return segment_clips, calls


def test_cut_clip_ok(tmp_path, monkeypatch):
    seg, calls = _true_ffmpeg(monkeypatch)
    out = tmp_path / "clip.mp4"
    res = seg.cut_clip("media.mp4", 1.5, 4.0, str(out))
    assert res["ok"] is True
    assert res["error"] is None
    assert res["start_s"] == 1.5 and res["end_s"] == 4.0
    assert calls[0][0] == "ffmpeg"
    assert calls[0][1:-1][0:4] == ["-y", "-ss", "1.500", "-to"]
    assert "-i" in calls[0] and "-c" in calls[0]
    assert Path(res["out_path"]).parent == tmp_path
    assert out.parent.exists()  # out dir created


def test_cut_clip_reports_ffmpeg_error_without_raising(tmp_path, monkeypatch):
    import subprocess

    from backend.pipeline.segment_clips import cut_clip

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "boom", "stdout": ""})(),
    )
    res = cut_clip("m.mp4", 0.0, 2.0, str(tmp_path / "c.mp4"))
    assert res["ok"] is False
    assert "boom" in res["error"]


def test_cut_clip_missing_ffmpeg_reports_error(tmp_path, monkeypatch):
    import subprocess

    from backend.pipeline.segment_clips import cut_clip

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()),
    )
    res = cut_clip("m.mp4", 0.0, 2.0, str(tmp_path / "c.mp4"), ffmpeg="no-such-ffmpeg")
    assert res["ok"] is False
    assert "no-such-ffmpeg" in res["error"]


def test_cut_clip_timeout(tmp_path, monkeypatch):
    import subprocess

    from backend.pipeline.segment_clips import cut_clip

    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=300)),
    )
    res = cut_clip("m.mp4", 0.0, 2.0, str(tmp_path / "c.mp4"))
    assert res["ok"] is False
    assert "timed out" in res["error"]


def test_cut_clip_validates_times(tmp_path):
    from backend.pipeline.segment_clips import cut_clip

    with pytest.raises(ValueError):
        cut_clip("m.mp4", -1.0, 2.0, str(tmp_path / "c.mp4"))
    with pytest.raises(ValueError):
        cut_clip("m.mp4", 5.0, 5.0, str(tmp_path / "c.mp4"))
    with pytest.raises(ValueError):
        cut_clip("m.mp4", 6.0, 2.0, str(tmp_path / "c.mp4"))


def test_cut_concept_clips_all_ok(tmp_path, monkeypatch):
    seg, _ = _true_ffmpeg(monkeypatch)
    concepts = [
        {"name": "Gradient Descent", "start_s": 1.0, "end_s": 3.0},
        {"name": "Loss Function", "start_s": 10.0, "end_s": 15.0},
    ]
    results = seg.cut_concept_clips("media.mp4", concepts, str(tmp_path))
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert results[0]["name"] == "Gradient Descent"
    # filename: safe name + start-end range
    assert results[0]["path"].endswith("Gradient Descent__1-3.mp4")
    assert results[1]["path"].endswith("Loss Function__10-15.mp4")


def test_cut_concept_clips_skips_missing_timestamps(tmp_path, monkeypatch):
    seg, calls = _true_ffmpeg(monkeypatch)
    concepts = [
        {"name": "No Times", "start_s": None, "end_s": None},
        {"name": "Valid", "start_s": 0.0, "end_s": 1.0},
    ]
    results = seg.cut_concept_clips("media.mp4", concepts, str(tmp_path))
    assert results[0]["ok"] is False
    assert results[0]["error"] == "missing timestamps"
    assert results[1]["ok"] is True
    assert len(calls) == 1  # only the valid concept reached ffmpeg


def test_cut_concept_clips_safe_filename(tmp_path, monkeypatch):
    seg, _ = _true_ffmpeg(monkeypatch)
    results = seg.cut_concept_clips(
        "media.mp4", [{"name": "PDE:ODE", "start_s": 0, "end_s": 2}], str(tmp_path)
    )
    assert results[0]["ok"] is True
    assert Path(results[0]["path"]).name == "PDE_ODE__0-2.mp4"


def test_clip_persistence():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.models import db as models

    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as s:
        lec = models.Lecture(course_id="ml1", title="t", status="ready")
        s.add(lec)
        s.commit()
        s.add(
            models.Clip(
                lecture_id=lec.id,
                concept_name="Gradient Descent",
                start_s=1.0,
                end_s=3.0,
                path="data/processed/clips/1/Gradient Descent__1-3.mp4",
                ok=1,
            )
        )
        s.commit()

    with Session() as s:
        clip = s.query(models.Clip).filter_by(lecture_id=lec.id).one()
        assert clip.concept_name == "Gradient Descent"
        assert clip.ok == 1
        assert clip.lecture.course_id == "ml1"  # relationship wired