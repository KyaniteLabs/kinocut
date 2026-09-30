"""Redirected diagnostics preserve runner behavior with bounded failure reads."""

import subprocess
import sys
import tempfile

import pytest

from kinocut.errors import ProcessingError
from kinocut.ffmpeg_helpers import _run_command
from kinocut.limits import FFMPEG_STDERR_DIAGNOSTIC_BYTES


def test_large_binary_failure_diagnostics_remain_on_disk_and_error_prefix_is_bounded():
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stderr.buffer.write(b'\\xffdecode failure ' * 100000); sys.exit(9)",
    ]
    with tempfile.TemporaryFile() as diagnostics:
        with pytest.raises(ProcessingError) as failure:
            _run_command(command, timeout=10, stderr_sink=diagnostics)
        assert failure.value.returncode == 9
        assert "decode failure" in str(failure.value)
        assert "\ufffd" in failure.value.full_stderr
        assert len(failure.value.full_stderr) <= FFMPEG_STDERR_DIAGNOSTIC_BYTES
        assert diagnostics.tell() == 0
        diagnostics.seek(0, 2)
        assert diagnostics.tell() > FFMPEG_STDERR_DIAGNOSTIC_BYTES


def test_redirected_success_retains_stdout_and_caller_can_check_diagnostics():
    command = [sys.executable, "-c", "import sys; print('result'); sys.stderr.write('diagnostic')"]
    with tempfile.TemporaryFile() as diagnostics:
        result = _run_command(command, timeout=10, stderr_sink=diagnostics)
        assert result.stdout == "result\n"
        assert result.stderr is None
        diagnostics.seek(0)
        assert diagnostics.read() == b"diagnostic"


def test_default_runner_still_captures_both_streams():
    result = _run_command(
        [
            sys.executable,
            "-c",
            "import sys; print('result'); sys.stderr.write('diagnostic')",
        ],
        timeout=10,
    )
    assert result.stdout == "result\n"
    assert result.stderr == "diagnostic"


def test_redirected_runner_timeout_keeps_existing_processing_error(monkeypatch):
    def timeout(*args, **kwargs):
        assert "capture_output" not in kwargs
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] is diagnostics
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    with tempfile.TemporaryFile() as diagnostics:
        monkeypatch.setattr(subprocess, "run", timeout)
        with pytest.raises(ProcessingError, match="timed out") as failure:
            _run_command([sys.executable, "-c", "pass"], timeout=1, stderr_sink=diagnostics)
        assert failure.value.returncode == -1
