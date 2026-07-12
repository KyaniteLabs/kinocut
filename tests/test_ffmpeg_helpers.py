"""Tests for shared FFmpeg helper contracts."""

import subprocess

import pytest


def test_ffprobe_timeout_constant_exists():
    from mcp_video import limits

    assert hasattr(limits, "FFPROBE_TIMEOUT")
    assert limits.FFPROBE_TIMEOUT > 0
    assert limits.FFPROBE_TIMEOUT < limits.DEFAULT_FFMPEG_TIMEOUT


def test_run_ffprobe_json_uses_named_timeout(monkeypatch):
    from mcp_video import ffmpeg_helpers
    from mcp_video.limits import FFPROBE_TIMEOUT

    captured = {}

    class Result:
        stdout = '{"format": {}, "streams": []}'

    def fake_run_command(cmd, timeout=0):
        captured["timeout"] = timeout
        return Result()

    monkeypatch.setattr(ffmpeg_helpers, "_run_command", fake_run_command)

    assert ffmpeg_helpers._run_ffprobe_json("/tmp/video.mp4") == {"format": {}, "streams": []}
    assert captured["timeout"] == FFPROBE_TIMEOUT


def test_validate_input_path_rejects_null_bytes():
    from mcp_video.errors import InputFileError
    from mcp_video.ffmpeg_helpers import _validate_input_path

    try:
        _validate_input_path("/tmp/video\x00.mp4")
        raise AssertionError("Expected InputFileError")
    except InputFileError as e:
        assert "null bytes" in str(e).lower()


def test_validate_input_path_rejects_nonexistent_file():
    from mcp_video.errors import InputFileError
    from mcp_video.ffmpeg_helpers import _validate_input_path

    try:
        _validate_input_path("/nonexistent/path/video.mp4")
        raise AssertionError("Expected InputFileError")
    except InputFileError:
        pass


def test_validate_output_path_rejects_null_bytes():
    from mcp_video.errors import MCPVideoError
    from mcp_video.ffmpeg_helpers import _validate_output_path

    try:
        _validate_output_path("/tmp/video\x00.mp4")
        raise AssertionError("Expected MCPVideoError")
    except MCPVideoError as e:
        assert "null bytes" in str(e).lower()


def test_validate_output_path_rejects_parent_relative_paths():
    from mcp_video.errors import MCPVideoError
    from mcp_video.ffmpeg_helpers import _validate_output_path

    try:
        _validate_output_path("../clips/output.mp4")
        raise AssertionError("Expected MCPVideoError")
    except MCPVideoError as e:
        assert "traversal" in str(e).lower()


def test_validate_output_path_accepts_safe_paths():
    from mcp_video.ffmpeg_helpers import _validate_output_path

    assert _validate_output_path("output.mp4") == "output.mp4"
    assert _validate_output_path("/tmp/output.mp4") == "/tmp/output.mp4"
    assert _validate_output_path("foo/bar/baz.mp4") == "foo/bar/baz.mp4"


def test_run_ffmpeg_prepends_runtime_binary_for_raw_args(monkeypatch):
    from mcp_video import ffmpeg_helpers

    captured = {}

    def fake_ffmpeg():
        return "/custom/ffmpeg"

    def fake_run(cmd, capture_output, text, timeout, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("mcp_video.engine_runtime_utils._ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(ffmpeg_helpers.subprocess, "run", fake_run)

    ffmpeg_helpers._run_ffmpeg(["-i", "input.mp4", "output.mp4"])

    assert captured["cmd"] == ["/custom/ffmpeg", "-y", "-i", "input.mp4", "output.mp4"]


def test_subprocess_helpers_propagate_inherited_descriptor_allowlist(monkeypatch):
    from mcp_video import ffmpeg_helpers

    inherited = []

    def fake_run(cmd, **kwargs):
        inherited.append(kwargs.get("pass_fds"))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ffmpeg_helpers.subprocess, "run", fake_run)
    ffmpeg_helpers._run_command(["ffprobe", "-version"], pass_fds=(17, 19))
    ffmpeg_helpers._run_ffmpeg(["-version"], pass_fds=(23,))

    assert inherited == [(17, 19), (23,)]


def test_run_ffmpeg_rejects_full_ffprobe_command():
    """The dual-mode signature was removed: full commands belong to _run_command."""
    from mcp_video import ffmpeg_helpers

    with pytest.raises(ValueError, match="raw FFmpeg arguments"):
        ffmpeg_helpers._run_ffmpeg(["ffprobe", "-v", "error", "video.mp4"])


def test_run_ffmpeg_rejects_full_ffmpeg_command():
    from mcp_video import ffmpeg_helpers

    with pytest.raises(ValueError, match="raw FFmpeg arguments"):
        ffmpeg_helpers._run_ffmpeg(["ffmpeg", "-y", "-i", "input.mp4", "output.mp4"])


def test_validate_output_path_rejects_system_prefixes():
    from mcp_video.errors import MCPVideoError
    from mcp_video.ffmpeg_helpers import _validate_output_path

    try:
        _validate_output_path("/etc/mcp-video-output.mp4")
        raise AssertionError("Expected MCPVideoError")
    except MCPVideoError as e:
        assert e.code == "unsafe_path"


def test_validate_output_path_rejects_sensitive_home_dotfiles(monkeypatch, tmp_path):
    from mcp_video.errors import MCPVideoError
    from mcp_video.ffmpeg_helpers import _validate_output_path

    monkeypatch.setenv("HOME", str(tmp_path))
    ssh_config = tmp_path / ".ssh" / "config"
    ssh_config.parent.mkdir()
    ssh_config.write_text("Host *\n")

    try:
        _validate_output_path(str(ssh_config))
        raise AssertionError("Expected MCPVideoError")
    except MCPVideoError as e:
        assert e.code == "unsafe_path"


def test_validate_output_path_rejects_symlink_targets(tmp_path):
    from mcp_video.errors import MCPVideoError
    from mcp_video.ffmpeg_helpers import _validate_output_path

    target = tmp_path / "target.mp4"
    target.write_text("not media")
    link = tmp_path / "link.mp4"
    link.symlink_to(target)

    try:
        _validate_output_path(str(link))
        raise AssertionError("Expected MCPVideoError")
    except MCPVideoError as e:
        assert e.code == "unsafe_path"


def test_validate_output_path_rejects_existing_non_media_file(tmp_path):
    from mcp_video.errors import MCPVideoError
    from mcp_video.ffmpeg_helpers import _validate_output_path

    existing = tmp_path / "notes.py"
    existing.write_text("print('do not overwrite')\n")

    try:
        _validate_output_path(str(existing))
        raise AssertionError("Expected MCPVideoError")
    except MCPVideoError as e:
        assert e.code == "unsafe_path"
