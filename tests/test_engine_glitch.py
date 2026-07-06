"""Tests for mcp_video/engine_glitch.py — eight FFmpeg glitch effects."""

from __future__ import annotations

import os
import subprocess

import pytest

from mcp_video.engine_glitch import (
    glitch_cmyk_split,
    glitch_datamoshing,
    glitch_macroblocking,
    glitch_rgb_shift,
    glitch_scanline_jitter,
    glitch_screen_tearing,
    glitch_turbulent_displacement,
    glitch_vhs_tracking,
)
from mcp_video.errors import InputFileError, ProcessingError
from mcp_video.models import EditResult


# ---------------------------------------------------------------------------
# Effect 1: RGB Shift
# ---------------------------------------------------------------------------


class TestGlitchRgbShift:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_rgb_shift("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "rgb_shift.mp4")
        result = glitch_rgb_shift(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_edit_result_with_metadata(self, sample_video, tmp_path):
        out = str(tmp_path / "rgb_shift_meta.mp4")
        result = glitch_rgb_shift(sample_video, out, amount=5.0, noise=0.5)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0
        assert result.resolution is not None
        assert result.size_mb is not None

    @pytest.mark.slow
    def test_with_noise(self, sample_video, tmp_path):
        out = str(tmp_path / "rgb_shift_noise.mp4")
        result = glitch_rgb_shift(sample_video, out, amount=5.0, noise=0.5)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_with_angle(self, sample_video, tmp_path):
        out = str(tmp_path / "rgb_shift_angle.mp4")
        result = glitch_rgb_shift(sample_video, out, amount=8.0, angle=45.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_zero_amount(self, sample_video, tmp_path):
        out = str(tmp_path / "rgb_shift_zero.mp4")
        result = glitch_rgb_shift(sample_video, out, amount=0.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 2: Scanline Jitter
# ---------------------------------------------------------------------------


class TestGlitchScanlineJitter:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_scanline_jitter("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "scanline.mp4")
        result = glitch_scanline_jitter(sample_video, out, jitter_amount=10.0, frequency=0.3)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_duration_metadata(self, sample_video, tmp_path):
        out = str(tmp_path / "scanline_meta.mp4")
        result = glitch_scanline_jitter(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_high_frequency(self, sample_video, tmp_path):
        out = str(tmp_path / "scanline_hi.mp4")
        result = glitch_scanline_jitter(sample_video, out, frequency=0.9)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_row_height_one(self, sample_video, tmp_path):
        out = str(tmp_path / "scanline_row1.mp4")
        result = glitch_scanline_jitter(sample_video, out, row_height=1)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 3: Screen Tearing
# ---------------------------------------------------------------------------


class TestGlitchScreenTearing:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_screen_tearing("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "screen_tearing.mp4")
        result = glitch_screen_tearing(sample_video, out, tear_count=3, offset_range=40.0)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_elapsed_ms(self, sample_video, tmp_path):
        out = str(tmp_path / "screen_tearing_meta.mp4")
        result = glitch_screen_tearing(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_single_tear(self, sample_video, tmp_path):
        out = str(tmp_path / "screen_tearing_one.mp4")
        result = glitch_screen_tearing(sample_video, out, tear_count=1)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 4: VHS Tracking
# ---------------------------------------------------------------------------


class TestGlitchVhsTracking:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_vhs_tracking("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "vhs.mp4")
        result = glitch_vhs_tracking(sample_video, out, tracking=0.5, noise_amount=0.02)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_elapsed_ms(self, sample_video, tmp_path):
        out = str(tmp_path / "vhs_meta.mp4")
        result = glitch_vhs_tracking(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_zero_noise(self, sample_video, tmp_path):
        out = str(tmp_path / "vhs_zero_noise.mp4")
        result = glitch_vhs_tracking(sample_video, out, noise_amount=0.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_max_tracking(self, sample_video, tmp_path):
        out = str(tmp_path / "vhs_max.mp4")
        result = glitch_vhs_tracking(sample_video, out, tracking=1.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 5: Macroblocking
# ---------------------------------------------------------------------------


class TestGlitchMacroblocking:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_macroblocking("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "macro.mp4")
        result = glitch_macroblocking(sample_video, out, block_size=16, intensity=0.7)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0
        # Resolution should be preserved (video gets scaled back to original)
        assert result.resolution == "640x480"

    @pytest.mark.slow
    def test_returns_elapsed_ms(self, sample_video, tmp_path):
        out = str(tmp_path / "macro_meta.mp4")
        result = glitch_macroblocking(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_small_blocks(self, sample_video, tmp_path):
        out = str(tmp_path / "macro_small.mp4")
        result = glitch_macroblocking(sample_video, out, block_size=4)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_minimum_block_size_clamped(self, sample_video, tmp_path):
        # block_size<2 gets clamped to 2 by the engine, should not raise
        out = str(tmp_path / "macro_clamped.mp4")
        result = glitch_macroblocking(sample_video, out, block_size=1)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 6: Datamoshing
# ---------------------------------------------------------------------------


class TestGlitchDatamoshing:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_datamoshing("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "datamosh.mp4")
        result = glitch_datamoshing(sample_video, out, drift=10.0, iframe_interval=15)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_elapsed_ms(self, sample_video, tmp_path):
        out = str(tmp_path / "datamosh_meta.mp4")
        result = glitch_datamoshing(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_zero_drift(self, sample_video, tmp_path):
        out = str(tmp_path / "datamosh_zero.mp4")
        result = glitch_datamoshing(sample_video, out, drift=0.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_iframe_interval_clamped_to_one(self, sample_video, tmp_path):
        # iframe_interval<1 gets clamped to 1 by the engine
        out = str(tmp_path / "datamosh_clamped.mp4")
        result = glitch_datamoshing(sample_video, out, iframe_interval=0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 7: CMYK Split
# ---------------------------------------------------------------------------


class TestGlitchCmykSplit:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_cmyk_split("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "cmyk.mp4")
        result = glitch_cmyk_split(sample_video, out, amount=5.0)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_elapsed_ms(self, sample_video, tmp_path):
        out = str(tmp_path / "cmyk_meta.mp4")
        result = glitch_cmyk_split(sample_video, out)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_with_noise(self, sample_video, tmp_path):
        out = str(tmp_path / "cmyk_noise.mp4")
        result = glitch_cmyk_split(sample_video, out, amount=5.0, noise=0.3)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_with_angle(self, sample_video, tmp_path):
        out = str(tmp_path / "cmyk_angle.mp4")
        result = glitch_cmyk_split(sample_video, out, amount=8.0, angle=30.0)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


# ---------------------------------------------------------------------------
# Effect 8: Turbulent Displacement
# ---------------------------------------------------------------------------


class TestGlitchTurbulentDisplacement:
    def test_rejects_nonexistent_input(self, tmp_path):
        with pytest.raises(InputFileError):
            glitch_turbulent_displacement("/nonexistent/video.mp4", str(tmp_path / "out.mp4"))

    @pytest.mark.slow
    def test_produces_output_file(self, sample_video, tmp_path):
        out = str(tmp_path / "turbulent.mp4")
        result = glitch_turbulent_displacement(sample_video, out, amount=10.0, octaves=2)
        assert isinstance(result, EditResult)
        assert result.success is True
        assert result.output_path == out
        assert os.path.isfile(out)
        assert result.duration > 0

    @pytest.mark.slow
    def test_returns_elapsed_ms(self, sample_video, tmp_path):
        out = str(tmp_path / "turbulent_meta.mp4")
        result = glitch_turbulent_displacement(sample_video, out, octaves=1)
        assert isinstance(result, EditResult)
        assert result.elapsed_ms is not None
        assert result.elapsed_ms > 0

    @pytest.mark.slow
    def test_single_octave(self, sample_video, tmp_path):
        out = str(tmp_path / "turbulent_1oct.mp4")
        result = glitch_turbulent_displacement(sample_video, out, octaves=1)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_max_octaves(self, sample_video, tmp_path):
        out = str(tmp_path / "turbulent_5oct.mp4")
        result = glitch_turbulent_displacement(sample_video, out, octaves=5)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)

    @pytest.mark.slow
    def test_octaves_clamped_above_five(self, sample_video, tmp_path):
        # octaves > 5 gets clamped to 5 in the engine
        out = str(tmp_path / "turbulent_clamped.mp4")
        result = glitch_turbulent_displacement(sample_video, out, octaves=10)
        assert isinstance(result, EditResult)
        assert os.path.isfile(result.output_path)


class TestGlitchShaderFpsProbe:
    def test_get_fps_uses_shared_runner_with_ffprobe_timeout(self, monkeypatch, tmp_path):
        import mcp_video.engine_glitch_shader as shader_engine
        from mcp_video.limits import FFPROBE_TIMEOUT

        calls = {}

        def fake_run_command(cmd, timeout):
            calls["cmd"] = cmd
            calls["timeout"] = timeout
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout='{"streams":[{"r_frame_rate":"24/1"}]}',
                stderr="",
            )

        monkeypatch.setattr(shader_engine, "_run_command", fake_run_command)

        assert shader_engine._get_fps(str(tmp_path / "input.mp4")) == "24/1"
        assert calls["cmd"][0] == "ffprobe"
        assert calls["timeout"] == FFPROBE_TIMEOUT

    def test_get_fps_propagates_probe_timeout_as_processing_error(self, monkeypatch, tmp_path):
        import mcp_video.engine_glitch_shader as shader_engine

        def fake_run_command(cmd, timeout):
            raise ProcessingError(" ".join(cmd), -1, f"FFmpeg command timed out after {timeout}s")

        monkeypatch.setattr(shader_engine, "_run_command", fake_run_command)

        with pytest.raises(ProcessingError, match="timed out"):
            shader_engine._get_fps(str(tmp_path / "hung.mp4"))

    def test_get_fps_propagates_nonzero_probe_as_processing_error(self, monkeypatch, tmp_path):
        import mcp_video.engine_glitch_shader as shader_engine

        def fake_run_command(cmd, timeout):
            raise ProcessingError(" ".join(cmd), 1, "Invalid data found when processing input")

        monkeypatch.setattr(shader_engine, "_run_command", fake_run_command)

        with pytest.raises(ProcessingError, match="Invalid data found"):
            shader_engine._get_fps(str(tmp_path / "corrupt.mp4"))

    def test_get_fps_sanitizes_malformed_probe_json(self, monkeypatch, tmp_path):
        import mcp_video.engine_glitch_shader as shader_engine

        def fake_run_command(cmd, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(shader_engine, "_run_command", fake_run_command)

        with pytest.raises(ProcessingError, match="Invalid JSON from ffprobe"):
            shader_engine._get_fps(str(tmp_path / "empty.mp4"))

    def test_get_fps_preserves_empty_stream_fallback(self, monkeypatch, tmp_path):
        import mcp_video.engine_glitch_shader as shader_engine

        def fake_run_command(cmd, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout='{"streams":[]}', stderr="")

        monkeypatch.setattr(shader_engine, "_run_command", fake_run_command)

        assert shader_engine._get_fps(str(tmp_path / "no-video.mp4")) == "30/1"
