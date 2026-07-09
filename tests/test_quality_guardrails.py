"""Tests for visual design quality guardrails."""

from __future__ import annotations

import os
import subprocess
import tempfile
from unittest.mock import Mock, patch

import pytest

from mcp_video import quality_check, VisualQualityGuardrails, QualityReport
from mcp_video.design_quality import design_quality_check


def create_test_video(output_path: str, color: str = "gray", duration: float = 2.0) -> str:
    """Create a test video with specified color background.

    Args:
        output_path: Path to save the video
        color: Color name (gray, black, white, red, green, blue)
        duration: Video duration in seconds

    Returns:
        Path to created video
    """
    # Map color names to ffmpeg color values
    color_map = {
        "gray": "gray",
        "black": "black",
        "white": "white",
        "red": "red",
        "green": "green",
        "blue": "blue",
        "yellow": "yellow",
        "cyan": "cyan",
        "magenta": "magenta",
    }

    ffmpeg_color = color_map.get(color, "gray")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={ffmpeg_color}:s=320x240:d={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration}",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create test video: {result.stderr}")
    return output_path


def create_video_no_audio(output_path: str, color: str = "gray", duration: float = 2.0) -> str:
    """Create a test video without audio."""
    ffmpeg_color = color
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={ffmpeg_color}:s=320x240:d={duration}",
        "-pix_fmt",
        "yuv420p",
        "-an",  # No audio
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create test video: {result.stderr}")
    return output_path


def create_colorful_test_video(output_path: str, duration: float = 2.0) -> str:
    """Create a colorful moving fixture with enough chroma/contrast for guardrails."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=320x240:rate=24:duration={duration}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration}",
        "-vf",
        "hue=s=1.4,eq=brightness=0.03:contrast=1.1",
        "-pix_fmt",
        "yuv420p",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create colorful test video: {result.stderr}")
    return output_path


class TestQualityReport:
    """Tests for QualityReport dataclass."""

    def test_quality_report_creation(self):
        """Test creating a QualityReport."""
        report = QualityReport(
            check_name="brightness", passed=True, score=85.0, message="Brightness is good", details={"y_avg": 128.0}
        )
        assert report.check_name == "brightness"
        assert report.passed is True
        assert report.score == 85.0
        assert report.message == "Brightness is good"
        assert report.details == {"y_avg": 128.0}

    def test_quality_report_default_details(self):
        """Test QualityReport with default empty details."""
        report = QualityReport(
            check_name="contrast",
            passed=False,
            score=45.0,
            message="Contrast too low",
        )
        assert report.details == {}


class TestVisualQualityGuardrails:
    """Tests for VisualQualityGuardrails class."""

    @pytest.fixture
    def guardrails(self):
        """Create a VisualQualityGuardrails instance."""
        return VisualQualityGuardrails()

    def test_initialization(self, guardrails):
        """Test guardrails initializes with correct thresholds."""
        assert guardrails.BRIGHTNESS_MIN == 16
        assert guardrails.BRIGHTNESS_MAX == 235
        assert guardrails.BRIGHTNESS_TARGET_MIN == 40
        assert guardrails.BRIGHTNESS_TARGET_MAX == 200
        assert guardrails.CONTRAST_MIN == 20
        assert guardrails.CONTRAST_MAX == 100
        assert guardrails.AUDIO_LUFS_TARGET == -16

    def test_check_brightness_with_gray_video(self, guardrails, tmp_path):
        """Test brightness check on a gray video."""
        video_path = str(tmp_path / "gray.mp4")
        create_test_video(video_path, "gray")

        report = guardrails.check_brightness(video_path)

        assert report.check_name == "brightness"
        assert isinstance(report.passed, bool)
        assert 0 <= report.score <= 100
        assert isinstance(report.message, str)
        assert "y_avg" in report.details or report.score == 0.0

    def test_check_brightness_with_black_video(self, guardrails, tmp_path):
        """Test brightness check on a black video (should fail)."""
        video_path = str(tmp_path / "black.mp4")
        create_test_video(video_path, "black")

        report = guardrails.check_brightness(video_path)

        assert report.check_name == "brightness"
        assert isinstance(report.score, float)
        if report.score > 0:  # If analysis succeeded
            assert report.score < 80  # Black video should have low score

    def test_check_contrast(self, guardrails, tmp_path):
        """Test contrast check."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = guardrails.check_contrast(video_path)

        assert report.check_name == "contrast"
        assert isinstance(report.score, float)
        assert 0 <= report.score <= 100
        assert isinstance(report.message, str)

    def test_check_saturation(self, guardrails, tmp_path):
        """Test saturation check."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = guardrails.check_saturation(video_path)

        assert report.check_name == "saturation"
        assert isinstance(report.score, float)
        assert 0 <= report.score <= 100

    def test_technical_and_design_checks_share_saturation_metric(self, tmp_path):
        video_path = str(tmp_path / "lime.mp4")
        create_test_video(video_path, "green", duration=0.5)

        technical = quality_check(video_path)
        design = design_quality_check(video_path)

        technical_metric = next(c for c in technical["checks"] if c["name"] == "saturation")["details"][
            "metric"
        ]
        design_metric = design["metrics"]["saturation"]
        assert technical_metric["name"] == design_metric["name"] == "ffmpeg.signalstats.SATAVG"
        assert technical_metric["unit"] == design_metric["unit"] == "percent_of_8bit_yuv_saturation_range"
        assert design_metric["value"] == pytest.approx(technical_metric["value"])

        technical_contrast = next(c for c in technical["checks"] if c["name"] == "contrast")["details"]["metric"]
        design_contrast = design["metrics"]["contrast"]
        assert technical_contrast["name"] == design_contrast["name"] == "ffmpeg.signalstats.YHIGH-YLOW"
        assert technical_contrast["unit"] == design_contrast["unit"] == "percent_of_8bit_luma_range"
        assert design_contrast["value"] == pytest.approx(technical_contrast["value"])

    def test_check_color_balance(self, guardrails, tmp_path):
        """Test color balance check."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = guardrails.check_color_balance(video_path)

        assert report.check_name == "color_balance"
        assert isinstance(report.score, float)
        assert 0 <= report.score <= 100
        assert isinstance(report.message, str)

    def test_check_color_balance_detects_red_cast(self, guardrails, tmp_path):
        """Test color balance detects red color cast."""
        video_path = str(tmp_path / "red.mp4")
        create_test_video(video_path, "red")

        report = guardrails.check_color_balance(video_path)

        if report.score > 0:  # If analysis succeeded
            # Red video should have red in color_cast or lower score
            details = report.details
            if details.get("color_cast"):
                assert "red" in details["color_cast"] or report.score < 70

    def test_colorful_fixture_has_usable_contrast_and_saturation(self, guardrails, tmp_path):
        """Dogfood-style colorful video should not fail due missing signalstats fields."""
        video_path = str(tmp_path / "colorful.mp4")
        create_colorful_test_video(video_path)

        contrast = guardrails.check_contrast(video_path)
        saturation = guardrails.check_saturation(video_path)
        color_balance = guardrails.check_color_balance(video_path)

        assert contrast.passed is True
        assert contrast.details["y_high"] > contrast.details["y_low"]
        assert saturation.passed is True
        assert saturation.details["sat_avg"] > 0
        assert color_balance.score > 0

    def test_bad_color_cast_fixture_fails_quality_gate(self, tmp_path):
        from mcp_video.quality_guardrails import assert_quality

        video_path = str(tmp_path / "green.mp4")
        create_test_video(video_path, "green")

        with pytest.raises(Exception, match="Quality gate failed"):
            assert_quality(video_path, min_score=95)

    def test_get_rgb_means_escapes_lavfi_path(self, guardrails):
        """RGB analysis should escape lavfi movie paths the same way as other ffprobe helpers."""
        special_path = "/tmp/with:comma,[brackets].mp4"
        fake = Mock(return_value=Mock(returncode=1, stdout="", stderr="bad path"))

        with patch("mcp_video.quality_guardrails.subprocess.run", fake):
            guardrails._get_rgb_means(special_path)

        cmd = fake.call_args.args[0]
        lavfi_arg = cmd[cmd.index("-i") + 1]
        assert lavfi_arg.startswith("movie=/tmp/with\\:comma\\,\\[brackets\\].mp4")

    def test_run_ffprobe_logs_nonzero_exit(self, guardrails):
        fake = Mock(return_value=Mock(returncode=1, stdout="", stderr="ffprobe failed"))
        with (
            patch("mcp_video.quality_guardrails.subprocess.run", fake),
            patch("mcp_video.quality_guardrails.logger.warning") as mock_warning,
        ):
            result = guardrails._run_ffprobe("/tmp/test.mp4", "lavfi.signalstats.YAVG")
            assert result["_error"]["stage"] == "ffprobe_signalstats"
        mock_warning.assert_called()

    def test_get_rgb_means_logs_nonzero_exit(self, guardrails):
        fake = Mock(return_value=Mock(returncode=1, stdout="", stderr="ffprobe failed"))
        with (
            patch("mcp_video.quality_guardrails.subprocess.run", fake),
            patch("mcp_video.quality_guardrails.logger.warning") as mock_warning,
        ):
            result = guardrails._get_rgb_means("/tmp/test.mp4")
            assert result["_error"]["stage"] == "ffprobe_rgb_means"
        mock_warning.assert_called()

    def test_analyze_loudnorm_logs_missing_json(self, guardrails):
        fake = Mock(return_value=Mock(returncode=0, stdout="", stderr="no structured data"))
        with (
            patch("mcp_video.quality_guardrails.subprocess.run", fake),
            patch("mcp_video.quality_guardrails.logger.warning") as mock_warning,
        ):
            result = guardrails._analyze_loudnorm("/tmp/test.mp4")
            assert result["_error"]["stage"] == "ffmpeg_loudnorm"
        mock_warning.assert_called()

    def test_check_color_balance_exposes_diagnostic_details(self, guardrails):
        with patch.object(guardrails, "_get_rgb_means", return_value={"_error": {"stage": "ffprobe_rgb_means"}}):
            report = guardrails.check_color_balance("/tmp/test.mp4")
        assert report.passed is False
        assert report.details["diagnostic"]["stage"] == "ffprobe_rgb_means"

    def test_check_brightness_exposes_fallback_diagnostic_details(self, guardrails):
        with (
            patch.object(guardrails, "_run_ffprobe", return_value={"_error": {"stage": "ffprobe_signalstats"}}),
            patch.object(
                guardrails, "_run_ffmpeg_signalstats", return_value={"_error": {"stage": "ffmpeg_signalstats"}}
            ),
        ):
            report = guardrails.check_brightness("/tmp/test.mp4")
        assert report.passed is False
        assert report.details["diagnostic"]["stage"] == "ffmpeg_signalstats"

    def test_check_audio_levels_with_audio(self, guardrails, tmp_path):
        """Test audio levels check on video with audio."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = guardrails.check_audio_levels(video_path)

        assert report.check_name == "audio_levels"
        assert isinstance(report.score, float)
        assert 0 <= report.score <= 100
        assert "lufs" in report.details or report.details.get("has_audio") is False

    def test_check_audio_levels_no_audio(self, guardrails, tmp_path):
        """Test audio levels check on video without audio."""
        video_path = str(tmp_path / "no_audio.mp4")
        create_video_no_audio(video_path, "gray")

        report = guardrails.check_audio_levels(video_path)

        assert report.check_name == "audio_levels"
        assert report.details.get("has_audio") is False
        assert report.passed is True
        assert report.score == 100.0

    def test_check_audio_levels_skips_loudnorm_for_silent_video(self, guardrails):
        """No-audio videos should not turn loudnorm missing JSON into a hard failure."""
        with (
            patch(
                "mcp_video.quality_guardrails._run_ffprobe_json", return_value={"streams": [{"codec_type": "video"}]}
            ),
            patch.object(guardrails, "_analyze_loudnorm") as loudnorm,
        ):
            report = guardrails.check_audio_levels("/tmp/silent.mp4")

        loudnorm.assert_not_called()
        assert report.passed is True
        assert report.details == {"has_audio": False}

    def test_check_audio_levels_reports_loudnorm_failure_when_audio_exists(self, guardrails):
        """Real audio streams should still fail when loudnorm analysis cannot produce metrics."""
        diagnostic = {"stage": "ffmpeg_loudnorm", "message": "ffmpeg loudnorm returned no JSON payload"}
        with (
            patch(
                "mcp_video.quality_guardrails._run_ffprobe_json", return_value={"streams": [{"codec_type": "audio"}]}
            ),
            patch.object(guardrails, "_analyze_loudnorm", return_value={"_error": diagnostic}),
        ):
            report = guardrails.check_audio_levels("/tmp/with-audio.mp4")

        assert report.passed is False
        assert report.details["has_audio"] is True
        assert report.details["diagnostic"] == diagnostic

    def test_run_all_checks(self, guardrails, tmp_path):
        """Test running all quality checks."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        checks = guardrails.run_all_checks(video_path)

        assert len(checks) == 6
        check_names = [c.check_name for c in checks]
        assert "brightness" in check_names
        assert "contrast" in check_names
        assert "saturation" in check_names
        assert "audio_levels" in check_names
        assert "color_balance" in check_names
        assert "temporal_motion" in check_names

    def test_generate_report(self, guardrails, tmp_path):
        """Test generating comprehensive quality report."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = guardrails.generate_report(video_path)

        assert "video" in report
        assert "overall_score" in report
        assert "all_passed" in report
        assert "checks" in report
        assert "recommendations" in report
        assert isinstance(report["overall_score"], (int, float))
        assert isinstance(report["all_passed"], bool)
        assert isinstance(report["checks"], list)
        assert len(report["checks"]) == 6
        assert report["video"] == video_path


class TestQualityCheckAPI:
    """Tests for the quality_check public API."""

    def test_quality_check_basic(self, tmp_path):
        """Test basic quality_check function."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = quality_check(video_path)

        assert "video" in report
        assert "overall_score" in report
        assert "all_passed" in report
        assert "checks" in report
        assert "recommendations" in report

    def test_quality_check_fail_on_warning(self, tmp_path):
        """Test quality_check with fail_on_warning=True."""
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = quality_check(video_path, fail_on_warning=True)

        assert "all_passed" in report
        # If overall score < 80, all_passed should be False
        if report["overall_score"] < 80:
            assert report["all_passed"] is False

    def test_fail_on_warning_preserves_failed_checks_above_score_threshold(self, tmp_path, monkeypatch):
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")
        monkeypatch.setattr(
            VisualQualityGuardrails,
            "generate_report",
            lambda self, video: {
                "video": video,
                "overall_score": 95.0,
                "all_passed": False,
                "checks": [{"name": "contrast", "passed": False}],
                "recommendations": ["Contrast check failed"],
            },
        )

        report = quality_check(video_path, fail_on_warning=True)

        assert report["all_passed"] is False

    def test_assert_quality_raises_on_low_score(self, tmp_path, monkeypatch):
        """Quality assertions should be usable as a hard workflow gate."""
        from mcp_video.quality_guardrails import assert_quality

        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        def fake_report(_video):
            return {
                "video": _video,
                "overall_score": 25.0,
                "all_passed": False,
                "checks": [],
                "recommendations": ["Color cast detected"],
            }

        monkeypatch.setattr(VisualQualityGuardrails, "generate_report", lambda self, video: fake_report(video))

        with pytest.raises(Exception, match="Quality gate failed"):
            assert_quality(video_path, min_score=80)

    def test_assert_quality_respects_custom_min_score_below_default(self, tmp_path, monkeypatch):
        """Custom release thresholds below the default should not be overridden by all_passed."""
        from mcp_video.quality_guardrails import assert_quality

        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        monkeypatch.setattr(
            VisualQualityGuardrails,
            "generate_report",
            lambda self, video: {
                "video": video,
                "overall_score": 70.0,
                "all_passed": False,
                "checks": [],
                "recommendations": ["Non-blocking for this custom threshold"],
            },
        )

        report = assert_quality(video_path, min_score=60)

        assert report["overall_score"] == 70.0
        assert report["all_passed"] is True

    def test_client_assert_quality_method_raises_on_low_score(self, tmp_path, monkeypatch):
        from mcp_video import Client

        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        monkeypatch.setattr(
            VisualQualityGuardrails,
            "generate_report",
            lambda self, video: {
                "video": video,
                "overall_score": 25.0,
                "all_passed": False,
                "checks": [],
                "recommendations": ["Color cast detected"],
            },
        )

        with pytest.raises(Exception, match="Quality gate failed"):
            Client().assert_quality(video_path, min_score=80)

    def test_quality_check_with_black_video(self, tmp_path):
        """Test quality_check on black video."""
        video_path = str(tmp_path / "black.mp4")
        create_test_video(video_path, "black")

        report = quality_check(video_path)

        assert "checks" in report
        # Should have recommendations for dark video
        assert isinstance(report["recommendations"], list)

    def test_quality_check_with_white_video(self, tmp_path):
        """Test quality_check on white video."""
        video_path = str(tmp_path / "white.mp4")
        create_test_video(video_path, "white")

        report = quality_check(video_path)

        assert "checks" in report
        # Should have recommendations for bright video
        brightness_check = None
        for check in report["checks"]:
            if check["name"] == "brightness":
                brightness_check = check
                break

        if brightness_check and brightness_check["score"] > 0:
            # White video should have lower brightness score
            assert brightness_check["score"] < 90


class TestClientIntegration:
    """Tests for Client.quality_check integration."""

    def test_client_quality_check_method(self, tmp_path):
        """Test that Client has quality_check method."""
        from mcp_video import Client

        client = Client()
        video_path = str(tmp_path / "test.mp4")
        create_test_video(video_path, "gray")

        report = client.quality_check(video_path)

        assert "overall_score" in report
        assert "checks" in report


@pytest.mark.skipif(
    subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0,
    reason="FFmpeg not installed",
)
class TestFFmpegAvailability:
    """Tests that require FFmpeg to be installed."""

    def test_ffmpeg_available(self):
        """Verify FFmpeg is available."""
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "ffmpeg version" in result.stdout.lower()

    def test_ffprobe_available(self):
        """Verify ffprobe is available."""
        result = subprocess.run(["ffprobe", "-version"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "ffprobe version" in result.stdout.lower()


if __name__ == "__main__":
    # Run a quick manual test
    with tempfile.TemporaryDirectory() as tmpdir:
        video = os.path.join(tmpdir, "test.mp4")
        create_test_video(video, "gray")

        report = quality_check(video)

        print(f"\n✓ Quality score: {report['overall_score']:.1f}/100")
        print(f"  All passed: {report['all_passed']}")
        print("\n  Individual checks:")
        for check in report["checks"]:
            status = "✓" if check["passed"] else "✗"
            print(f"    {status} {check['name']}: {check['score']:.1f} - {check['message']}")

        if report["recommendations"]:
            print("\n  Recommendations:")
            for rec in report["recommendations"]:
                print(f"    - {rec}")
        else:
            print("\n  No recommendations - video looks good!")
