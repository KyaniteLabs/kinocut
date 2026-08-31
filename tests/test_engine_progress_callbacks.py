"""Progress-callback coverage (extracted from tests/test_engine.py).

Second extraction to bring tests/test_engine.py under the 800-LOC module
ceiling; content unchanged.
"""

import os

import pytest

from mcp_video.engine import convert, _parse_ffmpeg_time


class TestProgressCallbacks:
    """Tests for progress callback functionality."""

    def test_parse_ffmpeg_time_parsing(self):
        """Test _parse_ffmpeg_time with various time formats."""
        # Format: HH:MM:SS.xx
        assert _parse_ffmpeg_time("00:00:05.12") == 5.12
        assert _parse_ffmpeg_time("00:01:30.00") == 90.0
        assert _parse_ffmpeg_time("00:00:00.00") == 0.0
        assert _parse_ffmpeg_time("01:00:00.00") == 3600.0
        assert _parse_ffmpeg_time("00:00:59.99") == 59.99

    def test_parse_ffmpeg_time_invalid_format(self):
        """Test _parse_ffmpeg_time with invalid format returns 0.0."""
        assert _parse_ffmpeg_time("invalid") == 0.0
        assert _parse_ffmpeg_time("00:00") == 0.0
        assert _parse_ffmpeg_time("") == 0.0

    def test_run_ffmpeg_with_progress_no_duration(self, sample_video, tmp_path):
        """When estimated_duration is None, should fall back to regular _run_ffmpeg."""
        from mcp_video.engine import _run_ffmpeg_with_progress
        import subprocess

        # Create a simple FFmpeg command
        output = str(tmp_path / "output.mp4")
        args = [
            "-i",
            sample_video,
            "-t",
            "1",
            "-c",
            "copy",
            output,
        ]

        # With estimated_duration=None, on_progress should not be called
        progress_calls = []

        def mock_on_progress(pct):
            progress_calls.append(pct)

        result = _run_ffmpeg_with_progress(args, estimated_duration=None, on_progress=mock_on_progress)
        assert isinstance(result, subprocess.CompletedProcess)
        # Progress callback should not have been called (falls back to regular _run_ffmpeg)
        assert len(progress_calls) == 0

    def test_run_ffmpeg_with_progress_convert(self, sample_video):
        """Use convert with on_progress callback, verify progress reaches 100."""
        progress_values = []

        def track_progress(pct):
            progress_values.append(pct)

        result = convert(sample_video, format="webm", on_progress=track_progress)

        # Verify the conversion succeeded
        assert os.path.isfile(result.output_path)
        assert result.format == "webm"

        # Verify progress was tracked and reached 100
        assert len(progress_values) > 0
        assert 100.0 in progress_values

    def test_run_ffmpeg_with_progress_propagates_callback_failure(self, sample_video, tmp_path):
        """Exceptions from progress callbacks must not disappear in stderr reader threads."""
        from mcp_video.engine import _run_ffmpeg_with_progress

        output = str(tmp_path / "callback_failure.mp4")
        args = [
            "-i",
            sample_video,
            "-t",
            "1",
            "-c",
            "copy",
            output,
        ]

        def fail_on_progress(pct):
            raise RuntimeError(f"progress failed at {pct}")

        with pytest.raises(RuntimeError, match="progress failed"):
            _run_ffmpeg_with_progress(args, estimated_duration=1.0, on_progress=fail_on_progress)

    def test_convert_returns_progress_field(self, sample_video):
        """Verify that convert returns EditResult with progress=100.0."""
        result = convert(sample_video, format="webm")
        assert result.progress == 100.0
        assert result.success is True
