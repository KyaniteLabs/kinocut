"""Real scene producer fixtures enforce frame and thumbnail resource ceilings."""

from __future__ import annotations

import shutil
import subprocess
import sys
from types import ModuleType

import pytest

from kinocut.ai_engine import scene
from kinocut.errors import MCPVideoError, ProcessingError


def _clip(tmp_path, size="64x64", seconds="3"):
    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is unavailable")
    path = tmp_path / "source.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={size}:r=2:d={seconds}",
            "-c:v",
            "ffv1",
            # Automatic slice selection can choose zero slices for a 2-pixel width.
            "-slices",
            "1",
            str(path),
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    return path


def _enable_ai(monkeypatch):
    pytest.importorskip("PIL.Image")
    monkeypatch.setitem(sys.modules, "imagehash", ModuleType("imagehash"))


def test_real_producer_stops_at_one_overflow_sentinel(tmp_path, monkeypatch):
    source = _clip(tmp_path)
    output = tmp_path / "frames"
    output.mkdir()
    monkeypatch.setattr(scene, "MAX_AI_SCENE_FRAMES", 2)
    with pytest.raises(MCPVideoError) as failure:
        scene._extract_scene_frames(str(source), str(output), 0.5)
    assert failure.value.code == "scene_frame_limit_exceeded"
    assert len(list(output.glob("frame_*.jpg"))) == 3


def test_inconsistent_metadata_overflow_is_not_hash_success_or_fallback(tmp_path, monkeypatch):
    source = _clip(tmp_path)
    _enable_ai(monkeypatch)
    monkeypatch.setattr(scene, "MAX_AI_SCENE_FRAMES", 2)
    monkeypatch.setattr(scene, "_run_ffprobe_json", lambda _: {"format": {"duration": "0.5"}})
    monkeypatch.setattr(scene, "_compute_frame_hashes", lambda *_: pytest.fail("partial scan was hashed"))
    monkeypatch.setattr(scene, "_standard_scene_detect", lambda *_: pytest.fail("overflow was hidden by fallback"))
    with pytest.raises(MCPVideoError) as failure:
        scene.ai_scene_detect(str(source), use_ai=True)
    assert failure.value.code == "scene_frame_limit_exceeded"


def test_exact_frame_ceiling_is_complete_success(tmp_path, monkeypatch):
    source = _clip(tmp_path, seconds="1")
    output = tmp_path / "frames"
    output.mkdir()
    monkeypatch.setattr(scene, "MAX_AI_SCENE_FRAMES", 2)
    frames = scene._extract_scene_frames(str(source), str(output), 0.5)
    assert len(frames) == 2


@pytest.mark.parametrize("size", ["2x256", "64x64", "160x90", "90x160"])
def test_real_thumbnail_geometry_is_bounded_and_preserves_common_aspects(tmp_path, size):
    image = pytest.importorskip("PIL.Image")
    source = _clip(tmp_path, size=size, seconds="0.5")
    output = tmp_path / "frames"
    output.mkdir()
    frames = scene._extract_scene_frames(str(source), str(output), 0.5)
    assert len(frames) == 1
    with image.open(frames[0]) as frame:
        width, height = frame.size
    assert 0 < width <= scene.MAX_AI_SCENE_FRAME_WIDTH
    assert 0 < height <= scene.MAX_AI_SCENE_FRAME_HEIGHT
    original_width, original_height = map(int, size.split("x"))
    if original_width != 2:
        assert width == 320
        assert abs(height - width * original_height / original_width) <= 1


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), -1, "nan", "-0.1", 10**10000, True, False, {}, [], "not-duration"],
    ids=[
        "nan",
        "inf",
        "negative-inf",
        "negative",
        "nan-string",
        "negative-string",
        "huge-int",
        "true",
        "false",
        "dict",
        "list",
        "invalid-string",
    ],
)
def test_invalid_duration_is_typed_and_never_starts_a_producer(tmp_path, monkeypatch, value):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"input existence validation remains active")
    _enable_ai(monkeypatch)
    monkeypatch.setattr(scene, "_run_ffprobe_json", lambda _: {"format": {"duration": value}})
    monkeypatch.setattr(scene, "_extract_scene_frames", lambda *_: pytest.fail("invalid duration started a producer"))
    with pytest.raises(MCPVideoError) as failure:
        scene.ai_scene_detect(str(source), use_ai=True)
    assert failure.value.code == "invalid_media_duration"


@pytest.mark.parametrize("value", [0, "0", None, ""])
def test_zero_or_absent_duration_preserves_existing_empty_result(value):
    assert scene._parse_duration(value) == 0.0


def test_processing_failure_still_uses_standard_fallback(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"input validation remains active")
    _enable_ai(monkeypatch)
    monkeypatch.setattr(scene, "_run_ffprobe_json", lambda _: {"format": {"duration": "1"}})

    def fail(*_args):
        raise ProcessingError("safe fixture", 1, "decoder unavailable")

    monkeypatch.setattr(scene, "_extract_scene_frames", fail)
    expected = [{"timestamp": 0.5, "frame": None}]
    monkeypatch.setattr(scene, "_standard_scene_detect", lambda *_: expected)
    assert scene.ai_scene_detect(str(source), use_ai=True) == expected
