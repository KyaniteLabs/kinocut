"""Real-media regressions for audio-only waveform/preflight and normalization."""

from pathlib import Path

import pytest

from kinocut.aivideo.preflight import build_preflight_report
from kinocut.engine_audio_normalize import _measurement, normalize_audio
from kinocut.engine_audio_waveform import audio_waveform
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json


def _tone(path: Path, channels: int = 2):
    _run_ffmpeg(
        ["-f", "lavfi", "-i", "sine=frequency=997:sample_rate=44100:duration=4", "-ac", str(channels), str(path)]
    )


@pytest.mark.parametrize("suffix,channels", [("wav", 1), ("wav", 2), ("mp3", 1), ("mp3", 2)])
def test_audio_only_waveform_and_preflight(tmp_path, suffix, channels):
    source = tmp_path / f"tone.{suffix}"
    _tone(source, channels)
    first, second = audio_waveform(str(source), bins=12), audio_waveform(str(source), bins=12)
    assert first == second
    assert not first.synthetic and len(first.peaks) > 0
    report = build_preflight_report(str(source))
    assert report.integrity.fully_decoded
    assert report.loudness.has_audio and report.loudness.integrated_lufs is not None
    assert not report.color.applicable and not report.color.analyzed
    assert not any(stream.codec_type == "video" for stream in report.technical.streams)


@pytest.mark.parametrize("suffix,codec", [("wav", "pcm_s16le"), ("m4a", "aac")])
def test_normalize_stereo_aac_to_actual_supported_container(tmp_path, suffix, codec):
    source, output = tmp_path / "input.m4a", tmp_path / f"normalized.{suffix}"
    _tone(source)
    original = source.read_bytes()
    result = normalize_audio(str(source), target_lufs=-18, output_path=str(output))
    info = _run_ffprobe_json(str(output))
    audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
    assert result.audio_codec == codec == audio["codec_name"]
    assert result.format == info["format"]["format_name"]
    assert audio["sample_rate"] == "44100" and audio["channels"] == 2
    assert float(info["format"]["duration"]) == pytest.approx(4, abs=0.08)
    measured = _measurement(
        _run_ffmpeg(
            ["-i", str(output), "-vn", "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
        ).stderr
    )
    assert measured["measured_I"] == pytest.approx(-18, abs=0.5)
    assert measured["measured_TP"] <= -1
    assert source.read_bytes() == original


def test_normalization_failed_postflight_preserves_existing_output(tmp_path, monkeypatch):
    source, output = tmp_path / "input.wav", tmp_path / "existing.wav"
    _tone(source)
    output.write_bytes(b"previous delivered artifact")

    def fail(*_args):
        raise MCPVideoError("Invalid normalized output", error_type="processing_error")

    monkeypatch.setattr("kinocut.engine_audio_normalize._validate_normalized_output", fail)
    with pytest.raises(MCPVideoError):
        normalize_audio(str(source), output_path=str(output))
    assert output.read_bytes() == b"previous delivered artifact"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_unsupported_normalization_container_rejected_before_execution(tmp_path, monkeypatch):
    source = tmp_path / "input.wav"
    _tone(source)
    monkeypatch.setattr("kinocut.engine_audio_normalize._run_ffmpeg", lambda *_args: pytest.fail("must not execute"))
    with pytest.raises(MCPVideoError, match="Unsupported"):
        normalize_audio(str(source), output_path=str(tmp_path / "out.invalid"))


def test_result_construction_failure_preserves_destination(tmp_path, monkeypatch):
    source, output = tmp_path / "input.wav", tmp_path / "existing.wav"
    _tone(source)
    output.write_bytes(b"delivered")

    def fail(*_args, **_kwargs):
        raise MCPVideoError("Result probe failed", error_type="processing_error")

    monkeypatch.setattr("kinocut.engine_audio_normalize._build_edit_result", fail)
    with pytest.raises(MCPVideoError):
        normalize_audio(str(source), output_path=str(output))
    assert output.read_bytes() == b"delivered"
    assert not list(tmp_path.glob(".kinocut_tmp_*"))


def test_audio_only_silent_waveform_is_measured_not_synthetic(tmp_path):
    source = tmp_path / "silence.wav"
    _run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", str(source)])
    result = audio_waveform(str(source), bins=8)
    assert not result.synthetic and result.peaks
    assert all(peak["level"] <= -59 for peak in result.peaks)
    assert result.silence_regions
