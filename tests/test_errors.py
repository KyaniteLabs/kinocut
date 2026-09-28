"""Tests for error classes and parse_ffmpeg_error — no FFmpeg needed."""

import pytest

from mcp_video.errors import (
    MCPVideoError,
    CodecError,
    FFmpegNotFoundError,
    FFprobeNotFoundError,
    InputFileError,
    ProcessingError,
    ResourceError,
    _strip_ffmpeg_banner,
    parse_ffmpeg_error,
)


class TestMCPVideoError:
    def test_to_dict_structure(self):
        err = MCPVideoError("something went wrong")
        d = err.to_dict()
        assert d["type"] == "unknown_error"
        assert d["code"] == "unknown"
        assert d["message"] == "something went wrong"
        assert "suggested_action" not in d
        assert "documentation_url" not in d

    def test_with_suggested_action(self):
        err = MCPVideoError(
            "test error",
            suggested_action={"auto_fix": True, "description": "try again"},
        )
        d = err.to_dict()
        assert "suggested_action" in d
        assert d["suggested_action"]["auto_fix"] is True

    def test_with_docs_url(self):
        err = MCPVideoError(
            "test error",
            docs_url="https://example.com/docs",
        )
        d = err.to_dict()
        assert "documentation_url" in d
        assert d["documentation_url"] == "https://example.com/docs"

    def test_is_exception(self):
        err = MCPVideoError("test")
        with pytest.raises(MCPVideoError):
            raise err

    def test_str_representation(self):
        err = MCPVideoError("detailed message")
        assert str(err) == "detailed message"


class TestFFmpegNotFoundError:
    def test_error_type(self):
        err = FFmpegNotFoundError()
        assert err.error_type == "dependency_error"
        assert err.code == "ffmpeg_not_found"

    def test_has_suggested_action(self):
        err = FFmpegNotFoundError()
        d = err.to_dict()
        assert "suggested_action" in d
        assert d["suggested_action"]["auto_fix"] is False

    def test_message_mentions_install(self):
        err = FFmpegNotFoundError()
        assert "install" in str(err).lower() or "Install" in str(err)


class TestFFprobeNotFoundError:
    def test_error_type(self):
        err = FFprobeNotFoundError()
        assert err.error_type == "dependency_error"
        assert err.code == "ffprobe_not_found"

    def test_message_mentions_ffprobe(self):
        err = FFprobeNotFoundError()
        assert "FFprobe" in str(err)


class TestInputFileError:
    def test_message_includes_path(self):
        err = InputFileError("/tmp/video.mp4")
        assert "/tmp/video.mp4" in str(err)

    def test_message_includes_reason(self):
        err = InputFileError("/tmp/video.mp4", "Permission denied")
        assert "Permission denied" in str(err)

    def test_error_type(self):
        err = InputFileError("/tmp/v.mp4")
        assert err.error_type == "input_error"
        assert err.code == "invalid_input"

    def test_has_suggested_action(self):
        err = InputFileError("/tmp/v.mp4")
        d = err.to_dict()
        assert "suggested_action" in d
        assert d["suggested_action"]["auto_fix"] is False

    def test_huge_path_is_truncated_not_echoed(self):
        # F4 regression: a 100 KB invalid path must not amplify into a
        # ~200 KB error reply echoing the caller's own garbage back.
        huge = "/tmp/" + "x" * 100_000 + ".mp4"
        err = InputFileError(huge)
        message = str(err)
        assert len(message) < 400
        assert "chars truncated" in message
        assert message.endswith(".mp4 — File not found (archivo no encontrado)")

    def test_to_dict_caps_oversized_messages(self):
        from mcp_video.errors import MCPVideoError

        err = MCPVideoError("boom: " + "y" * 10_000)
        d = err.to_dict()
        assert len(d["message"]) <= 2000
        assert "chars truncated" in d["message"]


class TestCodecError:
    def test_message_includes_codec(self):
        err = CodecError("vp9")
        assert "vp9" in str(err)

    def test_message_with_detail(self):
        err = CodecError("vp9", "not supported by encoder")
        assert "vp9" in str(err)
        assert "not supported by encoder" in str(err)

    def test_error_type(self):
        err = CodecError("h265")
        assert err.error_type == "encoding_error"
        assert err.code == "unsupported_codec"

    def test_auto_fix_true(self):
        err = CodecError("h265")
        d = err.to_dict()
        assert d["suggested_action"]["auto_fix"] is True
        assert "h265" in d["suggested_action"]["description"]

    def test_has_docs_url(self):
        err = CodecError("h265")
        d = err.to_dict()
        assert "documentation_url" in d


class TestProcessingError:
    def test_message_includes_returncode(self):
        err = ProcessingError("ffmpeg -i in.mp4 out.mp4", 1, "some error output")
        assert "exit code 1" in str(err)

    def test_truncated_stderr(self):
        long_stderr = "x" * 1000
        err = ProcessingError("cmd", 1, long_stderr)
        # Message should contain truncated version (last 500 chars)
        assert len(str(err)) < len(long_stderr) + 100

    def test_stores_full_stderr(self):
        long_stderr = "x" * 1000
        err = ProcessingError("cmd", 1, long_stderr)
        assert err.full_stderr == long_stderr
        assert len(err.full_stderr) == 1000

    def test_short_stderr_unchanged(self):
        stderr = "short error"
        err = ProcessingError("cmd", 1, stderr)
        assert stderr in str(err)

    def test_error_type(self):
        err = ProcessingError("cmd", 1, "err")
        assert err.error_type == "processing_error"
        assert err.code == "ffmpeg_exit_1"

    def test_stores_command(self):
        err = ProcessingError("ffmpeg -i a.mp4 b.mp4", 1, "err")
        assert err.command == "ffmpeg -i a.mp4 b.mp4"
        assert err.returncode == 1


class TestResourceError:
    def test_message_includes_resource_type(self):
        err = ResourceError("disk_space", "No space left")
        assert "disk_space" in str(err)
        assert "No space left" in str(err)

    def test_error_type(self):
        err = ResourceError("memory", "Out of memory")
        assert err.error_type == "resource_error"
        assert err.code == "insufficient_resource"


class TestParseFFmpegError:
    def test_no_such_file(self):
        err = parse_ffmpeg_error("Error: No such file or directory: /tmp/bad.mp4")
        assert isinstance(err, InputFileError)
        assert "File not found" in str(err)

    def test_invalid_data_found(self):
        err = parse_ffmpeg_error("Invalid data found when processing input")
        assert isinstance(err, InputFileError)
        assert "Not a valid video file" in str(err)

    def test_unsupported_codec(self):
        err = parse_ffmpeg_error("Decoder vp9 not found: unsupported codec")
        assert isinstance(err, CodecError)

    def test_decoder_error(self):
        err = parse_ffmpeg_error("Error while decoding stream: decoder error")
        assert isinstance(err, CodecError)

    def test_error_while_decoding(self):
        err = parse_ffmpeg_error("Error while decoding video frame")
        assert isinstance(err, ProcessingError)

    def test_permission_denied(self):
        err = parse_ffmpeg_error("Permission denied: /tmp/output.mp4")
        assert isinstance(err, InputFileError)
        assert "Permission denied" in str(err)

    def test_no_space_left(self):
        err = parse_ffmpeg_error("No space left on device")
        assert isinstance(err, ResourceError)
        assert "disk_space" in err.code or "disk" in str(err).lower()

    def test_unknown_error(self):
        err = parse_ffmpeg_error("Some random ffmpeg error we don't recognize")
        assert isinstance(err, ProcessingError)

    def test_case_insensitive(self):
        err = parse_ffmpeg_error("NO SUCH FILE OR DIRECTORY")
        assert isinstance(err, InputFileError)

    def test_preserves_stderr_in_processing_error(self):
        stderr = "detailed error trace here"
        err = parse_ffmpeg_error(stderr)
        assert isinstance(err, ProcessingError)
        assert err.full_stderr == stderr


class TestStripFFmpegBanner:
    def test_strips_version_banner(self):
        stderr = (
            "ffmpeg version 6.0\n"
            "built with gcc 12\n"
            "libavutil 58.2.100 / 58.2.100\n"
            "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'in.mp4':\n"
            "  Stream #0:0: Video: h264\n"
            "Error: something broke\n"
        )
        cleaned = _strip_ffmpeg_banner(stderr)
        assert "ffmpeg version" not in cleaned
        assert "libavutil" not in cleaned
        assert "Input #0" in cleaned
        assert "Error: something broke" in cleaned

    def test_preserves_permission_denied_in_banner(self):
        stderr = (
            "ffmpeg version 6.0\n"
            "built with gcc 12\n"
            "in.mp4: Permission denied\n"
            "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'in.mp4':\n"
        )
        cleaned = _strip_ffmpeg_banner(stderr)
        assert "Permission denied" in cleaned
        assert "ffmpeg version" not in cleaned

    def test_preserves_no_such_file_in_banner(self):
        stderr = "ffmpeg version 6.0\nNo such file or directory: missing.mp4\nStream mapping:\n"
        cleaned = _strip_ffmpeg_banner(stderr)
        assert "No such file or directory" in cleaned
        assert "ffmpeg version" not in cleaned

    def test_falls_back_to_original_when_everything_stripped(self):
        stderr = "ffmpeg version 6.0\nbuilt with gcc 12\n"
        cleaned = _strip_ffmpeg_banner(stderr)
        assert cleaned == stderr


class TestSanitizeFFmpegNumber:
    def test_rejects_nan(self):
        from mcp_video.ffmpeg_helpers import _sanitize_ffmpeg_number

        with pytest.raises(MCPVideoError) as exc_info:
            _sanitize_ffmpeg_number(float("nan"), "factor")
        assert "finite" in str(exc_info.value).lower()

    def test_rejects_inf(self):
        from mcp_video.ffmpeg_helpers import _sanitize_ffmpeg_number

        with pytest.raises(MCPVideoError) as exc_info:
            _sanitize_ffmpeg_number(float("inf"), "factor")
        assert "finite" in str(exc_info.value).lower()

    def test_rejects_neg_inf(self):
        from mcp_video.ffmpeg_helpers import _sanitize_ffmpeg_number

        with pytest.raises(MCPVideoError) as exc_info:
            _sanitize_ffmpeg_number(float("-inf"), "factor")
        assert "finite" in str(exc_info.value).lower()

    def test_accepts_valid_number(self):
        from mcp_video.ffmpeg_helpers import _sanitize_ffmpeg_number

        result = _sanitize_ffmpeg_number(2.5, "factor")
        assert result == 2.5
