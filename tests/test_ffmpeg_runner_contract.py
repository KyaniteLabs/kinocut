"""Contracts for the shared FFmpeg runners (Tier 3 convergence).

_run_ffmpeg takes raw arguments only; _run_command resolves bare binary names
the same way _run_ffmpeg does; parse_ffmpeg_error keeps the failing command's
input path instead of reporting an empty one.
"""

from __future__ import annotations

import subprocess

import pytest

import mcp_video.engine_runtime_utils as engine_runtime_utils
import mcp_video.ffmpeg_helpers as ffmpeg_helpers
from mcp_video.errors import InputFileError, parse_ffmpeg_error


def test_run_ffmpeg_rejects_full_commands():
    """The old magic first-element branch silently changed binary resolution
    and -y behavior; full commands now fail loudly."""
    with pytest.raises(ValueError, match="raw FFmpeg arguments"):
        ffmpeg_helpers._run_ffmpeg(["ffprobe", "-version"])


def test_run_command_resolves_bare_binary_names(monkeypatch):
    """_run_command used literal "ffprobe"/"ffmpeg", so the same server could
    find FFmpeg in one code path and miss it in another."""
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr("kinocut.bounded_process.run_bounded", fake_run)
    monkeypatch.setattr(engine_runtime_utils, "_ffprobe", lambda: "/resolved/bin/ffprobe")
    monkeypatch.setattr(engine_runtime_utils, "_ffmpeg", lambda: "/resolved/bin/ffmpeg")

    ffmpeg_helpers._run_command(["ffprobe", "-version"])
    assert captured["cmd"][0] == "/resolved/bin/ffprobe"

    ffmpeg_helpers._run_command(["ffmpeg", "-version"])
    assert captured["cmd"][0] == "/resolved/bin/ffmpeg"


def test_parse_ffmpeg_error_carries_input_path_from_command():
    err = parse_ffmpeg_error(
        "/data/in.mp4: No such file or directory",
        command=["/usr/bin/ffmpeg", "-y", "-i", "/data/in.mp4", "out.mp4"],
    )
    assert isinstance(err, InputFileError)
    assert "/data/in.mp4" in str(err)


def test_parse_ffmpeg_error_works_without_command_context():
    err = parse_ffmpeg_error("x.mp4: No such file or directory")
    assert isinstance(err, InputFileError)


def test_run_command_survives_non_utf8_subprocess_output():
    """Debian's ffmpeg 5.1 vidstab writes raw binary to stderr; strict UTF-8
    decoding crashed the whole operation with UnicodeDecodeError instead of
    surfacing a clean ProcessingError."""
    import sys

    from mcp_video.errors import ProcessingError

    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.buffer.write(b'\\xff\\xfe raw bytes'); sys.exit(1)",
    ]
    with pytest.raises(ProcessingError):
        ffmpeg_helpers._run_command(cmd)
