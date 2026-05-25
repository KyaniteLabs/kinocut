"""Tests for audio_guardrails module."""

import pytest

from mcp_video.audio_guardrails import validate_audio_mix
from mcp_video.errors import MCPVideoError
from mcp_video.models import VideoInfo


def _make_info(
    path: str = "test.mp4",
    duration: float = 5.0,
    audio_codec: str | None = "aac",
    audio_sample_rate: int | None = 48000,
) -> VideoInfo:
    return VideoInfo(
        path=path,
        duration=duration,
        width=320,
        height=240,
        fps=30.0,
        codec="h264",
        audio_codec=audio_codec,
        audio_sample_rate=audio_sample_rate,
    )


class TestValidateAudioMix:
    def test_same_props_no_warnings(self):
        source = _make_info()
        added = _make_info(path="audio.mp4")
        assert validate_audio_mix(source, added) == []

    def test_negative_volume_raises(self):
        source = _make_info()
        added = _make_info()
        with pytest.raises(MCPVideoError, match="volume must be >= 0"):
            validate_audio_mix(source, added, volume=-0.5)

    def test_high_volume_warns(self):
        source = _make_info()
        added = _make_info()
        warnings = validate_audio_mix(source, added, volume=2.0)
        assert any("clipping" in w.lower() for w in warnings)

    def test_sample_rate_mismatch_warns(self):
        source = _make_info(audio_sample_rate=48000)
        added = _make_info(path="audio.mp4", audio_sample_rate=44100)
        warnings = validate_audio_mix(source, added)
        assert any("Sample rate mismatch" in w for w in warnings)

    def test_no_audio_both_warns(self):
        source = _make_info(audio_codec=None, audio_sample_rate=None)
        added = _make_info(path="audio.mp4", audio_codec=None, audio_sample_rate=None)
        warnings = validate_audio_mix(source, added)
        assert any("Neither source nor added" in w for w in warnings)

    def test_start_time_past_duration_warns(self):
        source = _make_info(duration=5.0)
        added = _make_info(path="audio.mp4", duration=10.0)
        warnings = validate_audio_mix(source, added, start_time=10.0)
        assert any("exceeds source duration" in w for w in warnings)
