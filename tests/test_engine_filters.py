"""Tests for mcp_video/engine_filters.py — apply_filter and helpers."""

from __future__ import annotations

import os

import pytest

from mcp_video.engine_filters import (
    _build_pitch_shift_filter,
    _get_color_preset_filter,
    apply_filter,
)
from mcp_video.engine_probe import probe
from mcp_video.errors import InputFileError, MCPVideoError


def test_the_published_filter_vocabulary_matches_the_accepted_vocabulary() -> None:
    """The unknown-filter refusal publishes what apply_filter accepts — one set."""
    from typing import get_args

    import mcp_video.models as models

    from mcp_video.engine_filters import _filter_map

    accepted = _filter_map({}, 1920, 1080, 30.0)
    assert sorted(models.VALID_FILTER_TYPES) == sorted(accepted)
    assert sorted(models.VALID_FILTER_TYPES) == sorted(get_args(models.FilterType))


# ---------------------------------------------------------------------------
# _get_color_preset_filter (pure logic, no FFmpeg)
# ---------------------------------------------------------------------------


class TestGetColorPresetFilter:
    def test_returns_string_for_valid_presets(self):
        for preset in ("warm", "cool", "vintage", "cinematic", "noir"):
            result = _get_color_preset_filter(preset)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_raises_for_unknown_preset(self):
        with pytest.raises(MCPVideoError, match="Unknown color preset"):
            _get_color_preset_filter("unknown_preset")

    def test_warm_uses_eq(self):
        result = _get_color_preset_filter("warm")
        assert "eq=" in result

    def test_noir_contains_saturation_zero(self):
        result = _get_color_preset_filter("noir")
        assert "saturation=0.0" in result


# ---------------------------------------------------------------------------
# _build_pitch_shift_filter (pure logic, no FFmpeg)
# ---------------------------------------------------------------------------


class TestBuildPitchShiftFilter:
    def test_zero_semitones_contains_atempo(self):
        result = _build_pitch_shift_filter(0)
        assert "atempo=" in result
        assert "asetrate=" in result

    def test_positive_shift(self):
        result = _build_pitch_shift_filter(12)
        assert "asetrate=" in result

    def test_negative_shift(self):
        result = _build_pitch_shift_filter(-12)
        assert "asetrate=" in result

    def test_rejects_too_large_positive(self):
        with pytest.raises(MCPVideoError):
            _build_pitch_shift_filter(49)

    def test_rejects_too_large_negative(self):
        with pytest.raises(MCPVideoError):
            _build_pitch_shift_filter(-49)

    def test_boundary_positive_48(self):
        result = _build_pitch_shift_filter(48)
        assert isinstance(result, str)

    def test_boundary_negative_48(self):
        result = _build_pitch_shift_filter(-48)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# apply_filter — validation (no FFmpeg for unknown filter)
# ---------------------------------------------------------------------------


class TestApplyFilterValidation:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            apply_filter("/nonexistent/video.mp4", filter_type="grayscale")

    def test_rejects_unknown_filter_type(self, sample_video, tmp_path):
        with pytest.raises(MCPVideoError, match="Unknown filter type"):
            apply_filter(sample_video, filter_type="nonexistent_filter")

    def test_audio_filter_on_video_without_audio_raises(self, sample_video_no_audio, tmp_path):
        out = str(tmp_path / "reverb_no_audio.mp4")
        with pytest.raises(MCPVideoError, match="requires an audio stream"):
            apply_filter(sample_video_no_audio, filter_type="reverb", output_path=out)


# ---------------------------------------------------------------------------
# apply_filter — visual filters (needs FFmpeg, slow)
# ---------------------------------------------------------------------------


class TestApplyFilterVisual:
    @pytest.mark.slow
    def test_grayscale(self, sample_video, tmp_path):
        out = str(tmp_path / "gray.mp4")
        result = apply_filter(sample_video, filter_type="grayscale", output_path=out)
        assert os.path.isfile(result.output_path)
        info = probe(result.output_path)
        assert info.duration > 0

    @pytest.mark.slow
    def test_blur(self, sample_video, tmp_path):
        out = str(tmp_path / "blurred.mp4")
        result = apply_filter(sample_video, filter_type="blur", params={"radius": 3, "strength": 1}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_brightness(self, sample_video, tmp_path):
        out = str(tmp_path / "bright.mp4")
        result = apply_filter(sample_video, filter_type="brightness", params={"level": 0.1}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_contrast(self, sample_video, tmp_path):
        out = str(tmp_path / "contrast.mp4")
        result = apply_filter(sample_video, filter_type="contrast", params={"level": 1.3}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_saturation(self, sample_video, tmp_path):
        out = str(tmp_path / "saturated.mp4")
        result = apply_filter(sample_video, filter_type="saturation", params={"level": 1.5}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_sepia(self, sample_video, tmp_path):
        out = str(tmp_path / "sepia.mp4")
        result = apply_filter(sample_video, filter_type="sepia", output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_invert(self, sample_video, tmp_path):
        out = str(tmp_path / "inverted.mp4")
        result = apply_filter(sample_video, filter_type="invert", output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_color_preset_warm(self, sample_video, tmp_path):
        out = str(tmp_path / "warm.mp4")
        result = apply_filter(sample_video, filter_type="color_preset", params={"preset": "warm"}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_color_preset_noir(self, sample_video, tmp_path):
        out = str(tmp_path / "noir.mp4")
        result = apply_filter(sample_video, filter_type="color_preset", params={"preset": "noir"}, output_path=out)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# apply_filter — audio filters (needs FFmpeg, slow)
# ---------------------------------------------------------------------------


class TestApplyFilterAudio:
    @pytest.mark.slow
    def test_reverb(self, sample_video, tmp_path):
        out = str(tmp_path / "reverb.mp4")
        result = apply_filter(sample_video, filter_type="reverb", output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_pitch_shift_up(self, sample_video, tmp_path):
        out = str(tmp_path / "pitch_up.mp4")
        result = apply_filter(sample_video, filter_type="pitch_shift", params={"semitones": 3}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_pitch_shift_down(self, sample_video, tmp_path):
        out = str(tmp_path / "pitch_down.mp4")
        result = apply_filter(sample_video, filter_type="pitch_shift", params={"semitones": -3}, output_path=out)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_noise_reduction(self, sample_video, tmp_path):
        out = str(tmp_path / "denoised.mp4")
        result = apply_filter(sample_video, filter_type="noise_reduction", output_path=out)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# apply_filter — result properties
# ---------------------------------------------------------------------------


class TestApplyFilterResult:
    @pytest.mark.slow
    def test_result_has_operation(self, sample_video, tmp_path):
        out = str(tmp_path / "result_op.mp4")
        result = apply_filter(sample_video, filter_type="grayscale", output_path=out)
        assert "filter_grayscale" in result.operation

    @pytest.mark.slow
    def test_result_has_output_path(self, sample_video, tmp_path):
        out = str(tmp_path / "result_path.mp4")
        result = apply_filter(sample_video, filter_type="blur", output_path=out)
        assert result.output_path == out
