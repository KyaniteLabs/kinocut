"""Regression tests for design_quality probe fallback values.

When ffprobe/ffmpeg output parsing fails, _get_mean_luma and _get_contrast
must NOT return sentinel values (128/50) that produce perfect scores.
They should return None so callers can record uncertainty explicitly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class FakeCompletedProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture()
def guardrails():
    from mcp_video.design_quality.guardrails import DesignQualityGuardrails

    return DesignQualityGuardrails()


class TestGetMeanLumaFallback:
    """_get_mean_luma must not return 128 when parsing fails."""

    def test_returns_none_when_no_yavg_line(self, guardrails):
        """When ffmpeg stderr has no YAVG line, return None not 128."""
        with patch("mcp_video.design_quality.guardrails.probe.subprocess.run") as mock_run:
            mock_run.return_value = FakeCompletedProcess(
                stderr="frame=   10 fps=0.0 q=-1.0 N/A\nsome other output without signalstats\n",
            )
            result = guardrails._get_mean_luma("/tmp/nonexistent.mp4")
            assert result is None, f"Expected None on parse failure, got {result}"

    def test_returns_none_when_subprocess_fails(self, guardrails):
        """When ffmpeg returns non-zero exit, return None not 128."""
        with patch("mcp_video.design_quality.guardrails.probe.subprocess.run") as mock_run:
            mock_run.return_value = FakeCompletedProcess(
                stderr="Error opening input file\n",
                returncode=1,
            )
            result = guardrails._get_mean_luma("/tmp/nonexistent.mp4")
            assert result is None, f"Expected None on subprocess failure, got {result}"


class TestGetContrastFallback:
    """_get_contrast must not return 50 when parsing fails."""

    def test_returns_none_when_no_ystd_line(self, guardrails):
        """When ffmpeg stderr has no YSTD line, return None not 50."""
        with patch("mcp_video.design_quality.guardrails.probe.subprocess.run") as mock_run:
            mock_run.return_value = FakeCompletedProcess(
                stderr="frame=   10 fps=0.0 q=-1.0 N/A\nsome other output without signalstats\n",
            )
            result = guardrails._get_contrast("/tmp/nonexistent.mp4")
            assert result is None, f"Expected None on parse failure, got {result}"

    def test_returns_none_when_subprocess_fails(self, guardrails):
        """When ffmpeg returns non-zero exit, return None not 50."""
        with patch("mcp_video.design_quality.guardrails.probe.subprocess.run") as mock_run:
            mock_run.return_value = FakeCompletedProcess(
                stderr="Error opening input file\n",
                returncode=1,
            )
            result = guardrails._get_contrast("/tmp/nonexistent.mp4")
            assert result is None, f"Expected None on subprocess failure, got {result}"


class TestSaturationFallback:
    def test_missing_signalstats_is_explicitly_unavailable(self, guardrails):
        with patch("mcp_video.design_quality.guardrails.analysis.subprocess.run") as mock_run:
            mock_run.return_value = FakeCompletedProcess(stderr="no signalstats metadata")
            color_stats = guardrails._analyze_colors("/tmp/nonexistent.mp4")

        assert color_stats["saturation"] is None
        assert color_stats["saturation_metric"]["available"] is False

        with patch.object(guardrails, "_analyze_colors", return_value=color_stats):
            guardrails.issues = []
            guardrails._check_color("/tmp/nonexistent.mp4")

        assert any("Saturation analysis unavailable" in issue.message for issue in guardrails.issues)


class TestTechnicalScoreDoesNotRewardFailure:
    """When luma/contrast analysis fails, technical score must not be perfect."""

    def test_failed_luma_does_not_score_100(self, guardrails):
        """When _get_mean_luma returns None, brightness score should not be 100."""
        with (
            patch.object(guardrails, "_get_mean_luma", return_value=None),
            patch.object(guardrails, "_get_contrast", return_value=50),
            patch.object(guardrails, "_calculate_audio_score", return_value=50),
            patch.object(guardrails, "_analyze_colors", return_value={"rgb_means": [128, 128, 128], "saturation": 50}),
        ):
            score = guardrails._calculate_technical_score("/tmp/test.mp4")
            assert score < 100, f"Technical score should not be perfect when luma analysis failed, got {score}"

    def test_failed_contrast_does_not_score_100(self, guardrails):
        """When _get_contrast returns None, contrast score should not be 100."""
        with (
            patch.object(guardrails, "_get_mean_luma", return_value=128),
            patch.object(guardrails, "_get_contrast", return_value=None),
            patch.object(guardrails, "_calculate_audio_score", return_value=50),
            patch.object(guardrails, "_analyze_colors", return_value={"rgb_means": [128, 128, 128], "saturation": 50}),
        ):
            score = guardrails._calculate_technical_score("/tmp/test.mp4")
            assert score < 100, f"Technical score should not be perfect when contrast analysis failed, got {score}"


class TestProbeVideoStreamSelection:
    """Design quality probing must use the video stream, not the first stream."""

    def test_probe_selects_first_video_stream(self, guardrails):
        """ffprobe should explicitly select v:0 so audio-first MP4s do not produce 0/0 FPS."""
        with patch("mcp_video.design_quality.guardrails.probe.subprocess.run") as mock_run:
            mock_run.return_value = FakeCompletedProcess(
                stdout='{"streams":[{"width":1280,"height":720,"r_frame_rate":"30000/1001","duration":"8.0"}]}',
            )
            result = guardrails._probe_video("/tmp/audio-first.mp4")

        cmd = mock_run.call_args.args[0]
        assert "-select_streams" in cmd
        assert cmd[cmd.index("-select_streams") + 1] == "v:0"
        assert result["width"] == 1280

    def test_get_fps_falls_back_when_probe_reports_zero_rate(self, guardrails):
        """A 0/0 frame rate should not crash design quality scoring."""
        with patch.object(guardrails, "_probe_video", return_value={"r_frame_rate": "0/0"}):
            assert guardrails._get_fps("/tmp/audio-first.mp4") == 30.0


class TestCheckTypographyHandlesNone:
    """_check_typography must not silently pass when luma analysis fails."""

    def test_adds_issue_when_luma_is_none(self, guardrails):
        """When _get_mean_luma returns None, an advisory issue should be recorded."""
        with (
            patch.object(guardrails, "_get_mean_luma", return_value=None),
            patch.object(guardrails, "_analyze_colors", return_value={"rgb_means": [128, 128, 128], "saturation": 50}),
        ):
            guardrails.issues = []
            guardrails._check_typography("/tmp/test.mp4")
            categories = [i.category for i in guardrails.issues]
            assert "typography" in categories, (
                f"Expected a typography issue when luma analysis failed, got categories: {categories}"
            )
