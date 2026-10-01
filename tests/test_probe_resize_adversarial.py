"""Source identity, public applicability and non-destructive resize regressions."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kinocut import engine_probe, engine_resize
from kinocut.errors import InputFileError, MCPVideoError, ProcessingError
from kinocut.ffmpeg_helpers import _reset_operation_inputs
from kinocut.limits import MAX_RESOLUTION


@pytest.fixture(autouse=True)
def isolated_probe_operation():
    engine_probe.invalidate_probe_cache()
    _reset_operation_inputs()
    yield
    engine_probe.invalidate_probe_cache()
    _reset_operation_inputs()


def _equal_size_media(tmp_path, first: str, second: str):
    a, b = Path(first).read_bytes(), Path(second).read_bytes()
    size = max(len(a), len(b))
    source, replacement = tmp_path / "source.mp4", tmp_path / "replacement.mp4"
    source.write_bytes(a.ljust(size, b"\0"))
    replacement.write_bytes(b.ljust(size, b"\0"))
    return source, replacement


def test_probe_cache_detects_equal_size_equal_mtime_replacement(tmp_path, sample_video, sample_video_2):
    source, replacement = _equal_size_media(tmp_path, sample_video, sample_video_2)
    first = engine_probe.probe(str(source))
    before = source.stat()
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.replace(replacement, source)
    assert source.stat().st_size == before.st_size
    assert source.stat().st_mtime_ns == before.st_mtime_ns
    second = engine_probe.probe(str(source))
    assert (first.width, first.height) == (640, 480)
    assert (second.width, second.height) == (320, 240)


def test_probe_rejects_source_changed_during_measurement(tmp_path, sample_video, sample_video_2, monkeypatch):
    source, replacement = _equal_size_media(tmp_path, sample_video, sample_video_2)
    real_probe = engine_probe._run_ffprobe_json

    def replace_after_measurement(path):
        data = real_probe(path)
        os.replace(replacement, source)
        return data

    monkeypatch.setattr(engine_probe, "_run_ffprobe_json", replace_after_measurement)
    with pytest.raises(InputFileError, match="changed while probing"):
        engine_probe.probe(str(source))
    monkeypatch.setattr(engine_probe, "_run_ffprobe_json", real_probe)
    assert engine_probe.probe(str(source)).width == 320


def test_probe_cache_returns_defensive_copies_without_second_subprocess(sample_video, monkeypatch):
    real_probe = engine_probe._run_ffprobe_json
    calls = []

    def counted_probe(path):
        calls.append(path)
        return real_probe(path)

    monkeypatch.setattr(engine_probe, "_run_ffprobe_json", counted_probe)
    first = engine_probe.probe(sample_video)
    first.width = 0
    first.duration = -1
    second = engine_probe.probe_audio_input(sample_video)
    assert second.width == 640
    assert second.duration > 0
    assert len(calls) == 1
    second.width = 3
    assert engine_probe.probe(sample_video).width == 640


def test_audio_probe_cannot_change_video_applicability(sample_audio_wav):
    with pytest.raises(InputFileError, match="No video stream"):
        engine_probe.probe(sample_audio_wav)
    audio = engine_probe.probe_audio_input(sample_audio_wav)
    assert audio.width == 0 and audio.audio_codec is not None
    with pytest.raises(InputFileError, match="No video stream"):
        engine_probe.probe(sample_audio_wav)


@pytest.mark.parametrize("dimension", [0, -4, True, 1.5, float("nan"), float("inf"), MAX_RESOLUTION + 1])
@pytest.mark.parametrize("name", ["width", "height"])
def test_resize_single_dimension_has_structured_validation(sample_video, dimension, name, monkeypatch):
    def unexpected_render(*args, **kwargs):
        pytest.fail("Invalid dimensions reached FFmpeg")

    monkeypatch.setattr(engine_resize, "_run_ffmpeg", unexpected_render)
    with pytest.raises(MCPVideoError) as exc:
        engine_resize.resize(sample_video, **{name: dimension})
    assert exc.value.error_type == "validation_error"


def test_resize_bounds_aspect_derived_dimension(sample_video, monkeypatch):
    monkeypatch.setattr(engine_resize, "probe", lambda _: SimpleNamespace(width=1, height=MAX_RESOLUTION))
    with pytest.raises(MCPVideoError, match="resolved height"):
        engine_resize.resize(sample_video, width=MAX_RESOLUTION)


def test_resize_rejects_explicit_odd_dimensions_without_touching_delivery(tmp_path, sample_video):
    output = tmp_path / "delivered.mp4"
    output.write_bytes(Path(sample_video).read_bytes())
    before = output.read_bytes()
    with pytest.raises(MCPVideoError, match="must be even"):
        engine_resize.resize(sample_video, width=161, height=91, output_path=str(output))
    assert output.read_bytes() == before


def test_resize_real_encoding_failure_preserves_existing_delivery(tmp_path, sample_video, monkeypatch):
    output = tmp_path / "delivered.mp4"
    output.write_bytes(Path(sample_video).read_bytes())
    before = output.read_bytes()
    real_render = engine_resize._run_ffmpeg

    def unavailable_encoder(cmd):
        return real_render([*cmd[:-1], "-c:v", "kinocut_missing_encoder", cmd[-1]])

    monkeypatch.setattr(engine_resize, "_run_ffmpeg", unavailable_encoder)
    with pytest.raises(ProcessingError):
        engine_resize.resize(sample_video, width=160, height=90, output_path=str(output))
    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_resize_postflight_failure_preserves_existing_delivery(tmp_path, sample_video, monkeypatch):
    output = tmp_path / "delivered.mp4"
    output.write_bytes(Path(sample_video).read_bytes())
    before = output.read_bytes()

    def failed_postflight(*args, **kwargs):
        raise InputFileError("staged", "Postflight failed")

    monkeypatch.setattr(engine_resize, "_build_edit_result", failed_postflight)
    with pytest.raises(InputFileError, match="Postflight failed"):
        engine_resize.resize(sample_video, width=160, height=90, output_path=str(output))
    assert output.read_bytes() == before
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_valid_odd_single_dimension_rounds_even_and_keeps_public_path(tmp_path, sample_video):
    output = str(tmp_path / "resized.mp4")
    result = engine_resize.resize(sample_video, width=161, output_path=output)
    assert result.output_path == output
    assert result.elapsed_ms is not None and result.elapsed_ms > 0
    info = engine_probe.probe(output)
    assert info.width == 160 and info.height == 120


@pytest.mark.parametrize("rate", ["NaN", "inf", "-inf", "NaN/1", None])
def test_probe_frame_rate_is_finite_for_unavailable_metadata(rate):
    import math

    data = {"streams": [{"codec_type": "video", "width": 320, "height": 240, "r_frame_rate": rate}]}
    assert math.isfinite(engine_probe._build_video_info("fixture.mp4", data).fps)


def test_single_dimension_resize_uses_rotated_display_geometry(tmp_path, sample_video_2):
    from kinocut.ffmpeg_helpers import _run_ffmpeg

    rotated, output = str(tmp_path / "rotated.mp4"), str(tmp_path / "upright.mp4")
    _run_ffmpeg(["-display_rotation:v:0", "90", "-i", sample_video_2, "-c", "copy", rotated])
    source_info = engine_probe.probe(rotated)
    assert source_info.display_width == 240 and source_info.display_height == 320
    result = engine_resize.resize(rotated, width=300, output_path=output)
    assert result.resolution == "300x400"
    assert engine_probe.probe(output).display_resolution == "300x400"
