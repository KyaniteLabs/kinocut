"""Adversarial security test suite for Kinocut (formerly mcp-video).

Tests injection prevention, error handling robustness, input validation,
parameter bounds, and consistency across all engines.
"""

from __future__ import annotations

import contextlib
import pytest

from mcp_video.engine import (
    _validate_color,
    _validate_position,
    _escape_ffmpeg_filter_value,
)
from mcp_video.errors import (
    MCPVideoError,
    InputFileError,
    ProcessingError,
    wrap_error,
)


# ---------------------------------------------------------------------------
# Phase 0: Error Handling Robustness
# ---------------------------------------------------------------------------


class TestErrorHandlingRobustness:
    """_error_result handles all exception types."""

    def test_wrap_error_mcpvideoerror(self) -> None:
        """wrap_error returns MCPVideoError as-is."""
        original = InputFileError("/tmp/test.mp4")
        result = wrap_error(original)
        assert result is original

    def test_wrap_error_generic_exception(self) -> None:
        """wrap_error converts generic Exception to ProcessingError."""
        original = RuntimeError("something broke")
        result = wrap_error(original)
        assert isinstance(result, ProcessingError)
        assert "something broke" in str(result) or "something broke" in result.command

    def test_wrap_error_value_error(self) -> None:
        """wrap_error converts ValueError to ProcessingError."""
        original = ValueError("bad value")
        result = wrap_error(original)
        assert isinstance(result, ProcessingError)

    def test_server_error_result_mcpvideoerror(self) -> None:
        """_error_result handles MCPVideoError correctly."""
        from mcp_video.server import _error_result

        err = InputFileError("/tmp/nonexistent.mp4")
        result = _error_result(err)
        assert result["success"] is False
        assert "error" in result
        assert result["error"]["type"] == "input_error"

    def test_server_error_result_generic_exception(self) -> None:
        """_error_result handles generic Exception without crash — sanitized for no detail leak."""
        from mcp_video.server import _error_result

        err = RuntimeError("unexpected failure")
        result = _error_result(err)
        assert result["success"] is False
        assert "error" in result
        assert result["error"]["code"] == "internal_error"
        assert result["error"]["type"] == "internal_error"
        # Generic exceptions should NOT expose raw message
        assert "unexpected failure" not in result["error"]["message"]


# ---------------------------------------------------------------------------
# Phase 1: FFmpeg Filter Injection Prevention
# ---------------------------------------------------------------------------


class TestFFmpegFilterInjection:
    """No FFmpeg filter injection possible through user inputs."""

    # --- Position injection ---

    def test_position_dict_string_x_rejected(self) -> None:
        """String values in position x are rejected."""
        with pytest.raises(MCPVideoError, match="Invalid position"):
            _validate_position({"x": "BAD;malicious", "y": 0})

    def test_position_dict_string_y_rejected(self) -> None:
        """String values in position y are rejected."""
        with pytest.raises(MCPVideoError, match="Invalid position"):
            _validate_position({"x": 0, "y": "INJECT"})

    def test_position_pct_out_of_range_high(self) -> None:
        """Percentage > 1.0 is rejected."""
        with pytest.raises(MCPVideoError, match="Invalid position"):
            _validate_position({"x_pct": 2.0, "y_pct": 0.5})

    def test_position_pct_out_of_range_negative(self) -> None:
        """Negative percentage is rejected."""
        with pytest.raises(MCPVideoError, match="Invalid position"):
            _validate_position({"x_pct": -0.5, "y_pct": 0.5})

    def test_position_pct_string_rejected(self) -> None:
        """String values in percentage positions are rejected."""
        with pytest.raises(MCPVideoError, match="Invalid position"):
            _validate_position({"x_pct": "evil", "y_pct": 0.5})

    def test_position_valid_pixels_accepted(self) -> None:
        """Valid pixel positions pass validation."""
        _validate_position({"x": 100, "y": 50})  # Should not raise

    def test_position_valid_pct_accepted(self) -> None:
        """Valid percentage positions pass validation."""
        _validate_position({"x_pct": 0.5, "y_pct": 0.5})  # Should not raise

    def test_position_named_string_accepted(self) -> None:
        """Named position strings pass validation."""
        _validate_position("center")  # Should not raise

    # --- Color injection ---

    def test_color_injection_colon_rejected(self) -> None:
        """Color with FFmpeg special char ':' is rejected."""
        with pytest.raises(MCPVideoError, match="invalid_color"):
            _validate_color("white:text=INJECTED")

    def test_color_injection_bracket_rejected(self) -> None:
        """Color with FFmpeg special char '[' is rejected."""
        with pytest.raises(MCPVideoError, match="invalid_color"):
            _validate_color("white[evil]")

    def test_color_injection_semicolon_rejected(self) -> None:
        """Color with FFmpeg special char ';' is rejected."""
        with pytest.raises(MCPVideoError, match="invalid_color"):
            _validate_color("white';evil")

    def test_color_valid_hex_short(self) -> None:
        """Valid 3-char hex color accepted."""
        _validate_color("#F00")  # Should not raise

    def test_color_valid_hex_full(self) -> None:
        """Valid 6-char hex color accepted."""
        _validate_color("#FF0000")  # Should not raise

    def test_color_valid_hex_alpha(self) -> None:
        """Valid 8-char hex color with alpha accepted."""
        _validate_color("#FF000080")  # Should not raise

    def test_color_valid_named(self) -> None:
        """Valid CSS named color accepted."""
        _validate_color("white")  # Should not raise
        _validate_color("red")  # Should not raise
        _validate_color("DarkBlue")  # Case-insensitive

    def test_color_invalid_value_rejected(self) -> None:
        """Invalid color value rejected."""
        with pytest.raises(MCPVideoError, match="invalid_color"):
            _validate_color("notacolor123")


# ---------------------------------------------------------------------------
# Phase 2: Error Type Consistency
# ---------------------------------------------------------------------------


class TestErrorTypeConsistency:
    """All engines raise MCPVideoError subtypes."""

    def test_effects_engine_raises_processing_error(self) -> None:
        """effects_engine raises MCPVideoError (InputFileError), not RuntimeError."""
        from mcp_video.effects_engine import effect_vignette

        with pytest.raises(MCPVideoError):
            effect_vignette("/nonexistent/video.mp4", "/tmp/out.mp4")

    def test_transitions_engine_raises_processing_error(self) -> None:
        """transitions_engine raises MCPVideoError (InputFileError), not RuntimeError."""
        from mcp_video.transitions_engine import transition_pixelate

        with pytest.raises(MCPVideoError):
            transition_pixelate(
                "/nonexistent/clip1.mp4",
                "/nonexistent/clip2.mp4",
                "/tmp/out.mp4",
            )

    def test_wrap_error_preserves_processing_error(self) -> None:
        """wrap_error keeps ProcessingError details."""
        err = ProcessingError("ffmpeg -i test.mp4", 1, "No such file")
        result = wrap_error(err)
        assert isinstance(result, ProcessingError)
        assert result.returncode == 1


class TestFilesystemSafety:
    """MCP-facing destructive helpers stay inside safe file operations."""

    def test_video_cleanup_rejects_unmanaged_file(self, tmp_path) -> None:
        from mcp_video.server_tools_advanced import video_cleanup

        victim = tmp_path / "important.mp4"
        victim.write_bytes(b"keep")

        result = video_cleanup([str(victim)])

        assert result["success"] is False
        assert result["failed"] == 1
        assert victim.exists()
        assert result["results"][0]["status"] == "failed"
        assert "managed" in result["results"][0]["error"].lower()

    def test_video_cleanup_allows_mcp_video_intermediate(self, tmp_path) -> None:
        from mcp_video.server_tools_advanced import video_cleanup

        intermediate = tmp_path / "clip_trimmed.mp4"
        intermediate.write_bytes(b"generated")

        result = video_cleanup([str(intermediate)])

        assert result["success"] is True
        assert result["removed"] == 1
        assert not intermediate.exists()


class TestTimeoutProtection:
    """All FFmpeg calls have timeouts."""

    def test_effects_engine_has_timeout(self) -> None:
        """effects_engine subprocess.run calls include timeout parameter."""
        import inspect
        from mcp_video import ffmpeg_helpers

        # Timeout lives in the shared ffmpeg_helpers module used by effects_engine
        source = inspect.getsource(ffmpeg_helpers)
        assert "timeout=" in source or "timeout =" in source

    def test_transitions_engine_has_timeout(self) -> None:
        """transitions_engine subprocess.run calls include timeout parameter."""
        import inspect
        from mcp_video import ffmpeg_helpers

        # Timeout lives in the shared ffmpeg_helpers module used by transitions_engine
        source = inspect.getsource(ffmpeg_helpers)
        assert "timeout=" in source or "timeout =" in source


# ---------------------------------------------------------------------------
# Phase 3: Path Validation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 3: Parameter Bounds
# ---------------------------------------------------------------------------


class TestParameterBounds:
    """Numeric parameters are bounded."""

    def test_audio_frequency_too_low(self) -> None:
        """Frequency below 20 Hz is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Ff]requency"):
            audio_synthesize("/tmp/test.wav", frequency=5)

    def test_audio_frequency_too_high(self) -> None:
        """Frequency above 20000 Hz is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Ff]requency"):
            audio_synthesize("/tmp/test.wav", frequency=50000)

    def test_audio_frequency_zero(self) -> None:
        """Frequency of 0 Hz is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Ff]requency"):
            audio_synthesize("/tmp/test.wav", frequency=0)

    def test_audio_duration_too_short(self) -> None:
        """Duration below 0.01s is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Dd]uration"):
            audio_synthesize("/tmp/test.wav", duration=0.001)

    def test_audio_duration_too_long(self) -> None:
        """Duration above MAX_AUDIO_DURATION is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Dd]uration"):
            audio_synthesize("/tmp/test.wav", duration=100000)

    def test_audio_volume_negative(self) -> None:
        """Negative volume is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Vv]olume"):
            audio_synthesize("/tmp/test.wav", volume=-0.5)

    def test_audio_volume_over_one(self) -> None:
        """Volume > 1.0 is rejected."""
        from mcp_video.audio_engine import audio_synthesize

        with pytest.raises(MCPVideoError, match=r"[Vv]olume"):
            audio_synthesize("/tmp/test.wav", volume=1.5)

    def test_audio_synthesize_rejects_unknown_effect_key(self, tmp_path) -> None:
        """Unknown synth effect keys are rejected before producing output."""
        from mcp_video.audio_engine import audio_synthesize

        output = tmp_path / "out.wav"
        with pytest.raises(MCPVideoError, match="effects"):
            audio_synthesize(str(output), effects={"bitcrush": 0.5})
        assert not output.exists()

    def test_audio_valid_bounds(self) -> None:
        """Valid bounds at edges are accepted."""
        from mcp_video.audio_engine import audio_synthesize
        from mcp_video.limits import MIN_FREQUENCY

        # These should NOT raise - just validate params, don't actually run
        # We can't easily test without creating a file, so just test validation
        # by checking the function doesn't raise at boundary values
        with contextlib.suppress(ProcessingError, FileNotFoundError, OSError):
            audio_synthesize(
                "/tmp/test.wav",
                frequency=MIN_FREQUENCY,
                duration=0.01,
                volume=0.0,
            )


# ---------------------------------------------------------------------------
# Phase 3: Limits Module
# ---------------------------------------------------------------------------


class TestLimitsModule:
    """Centralized limits are defined."""

    def test_limits_importable(self) -> None:
        """Limits module can be imported."""
        from mcp_video import limits

        assert hasattr(limits, "MAX_VIDEO_DURATION")
        assert hasattr(limits, "MAX_RESOLUTION")
        assert hasattr(limits, "MAX_FILE_SIZE_MB")
        assert hasattr(limits, "DEFAULT_FFMPEG_TIMEOUT")
        assert hasattr(limits, "MAX_BATCH_SIZE")

    def test_limits_have_reasonable_values(self) -> None:
        """Limit values are reasonable."""
        from mcp_video.limits import (
            MAX_VIDEO_DURATION,
            MAX_RESOLUTION,
            MAX_FILE_SIZE_MB,
            DEFAULT_FFMPEG_TIMEOUT,
            MAX_BATCH_SIZE,
            MAX_AUDIO_DURATION,
        )

        assert MAX_VIDEO_DURATION > 0
        assert MAX_RESOLUTION > 0
        assert MAX_FILE_SIZE_MB > 0
        assert DEFAULT_FFMPEG_TIMEOUT > 0
        assert MAX_BATCH_SIZE > 0
        assert MAX_AUDIO_DURATION > 0


# ---------------------------------------------------------------------------
# Phase 4: Escaping Consistency
# ---------------------------------------------------------------------------


class TestEscapingConsistency:
    """Escaping is consistent across functions."""

    def test_escape_filter_value_escapes_backslash(self) -> None:
        """Backslashes are escaped for FFmpeg filter safety."""
        result = _escape_ffmpeg_filter_value("C:\\Users\\test")
        # Backslashes must be escaped so FFmpeg doesn't interpret them as escapes
        assert "\\\\" in result  # \ becomes \\

    def test_escape_filter_value_escapes_colon(self) -> None:
        """Colons are escaped."""
        result = _escape_ffmpeg_filter_value("/path/to:file")
        assert "\\:" in result

    def test_escape_filter_value_escapes_brackets(self) -> None:
        """Brackets are escaped."""
        result = _escape_ffmpeg_filter_value("file[0]")
        assert "\\[" in result
        assert "\\]" in result

    def test_escape_filter_value_escapes_comma(self) -> None:
        """Commas are escaped."""
        result = _escape_ffmpeg_filter_value("file,name")
        assert "\\," in result

    def test_escape_filter_value_escapes_equals(self) -> None:
        """Equals signs are escaped."""
        result = _escape_ffmpeg_filter_value("key=value")
        assert "\\=" in result

    def test_escape_filter_value_plain_path(self) -> None:
        """Plain paths without special chars pass through (except \\ to /)."""
        result = _escape_ffmpeg_filter_value("/tmp/test.mp4")
        assert result == "/tmp/test.mp4"

    def test_lavfi_path_escaping_in_guardrails(self) -> None:
        """quality_guardrails uses escaped paths for movie= filter."""
        import inspect
        from mcp_video import quality_guardrails

        source = inspect.getsource(quality_guardrails)
        assert "_escape_lavfi_path" in source
