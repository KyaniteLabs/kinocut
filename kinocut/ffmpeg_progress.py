"""Owned FFmpeg progress process with bounded chunk diagnostics and cancellation."""

from __future__ import annotations

import re
import contextlib
import subprocess
import threading
from collections.abc import Callable

from .defaults import DEFAULT_FFMPEG_PROGRESS_READER_JOIN_TIMEOUT
from .errors import ProcessingError, parse_ffmpeg_error
from .limits import (
    DEFAULT_FFMPEG_TIMEOUT,
    FFMPEG_PROGRESS_LINE_BYTES,
    FFMPEG_PROGRESS_READ_BYTES,
    FFMPEG_PROGRESS_STDERR_BYTES,
)

_TIME_RE = re.compile(r"time=(\d+:\d+:\d+\.\d+)")


def _stop(proc):
    if proc.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    proc.wait(timeout=DEFAULT_FFMPEG_PROGRESS_READER_JOIN_TIMEOUT)


class _Diagnostics:
    def __init__(self, proc, duration, callback, parse_time):
        self.proc, self.duration, self.callback, self.parse_time = proc, duration, callback, parse_time
        self.prefix, self.pending, self.errors = bytearray(), bytearray(), []

    def read(self):
        try:
            while self.proc.stderr is not None:
                chunk = self.proc.stderr.read1(FFMPEG_PROGRESS_READ_BYTES)
                if not chunk:
                    break
                space = FFMPEG_PROGRESS_STDERR_BYTES - len(self.prefix)
                self.prefix.extend(chunk[: max(0, space)])
                self.pending.extend(chunk)
                self._lines()
                if len(self.pending) > FFMPEG_PROGRESS_LINE_BYTES:
                    del self.pending[:-FFMPEG_PROGRESS_LINE_BYTES]
            self._progress(bytes(self.pending))
        except BaseException as exc:
            self.errors.append(exc)
            if self.proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    self.proc.kill()

    def _lines(self):
        while True:
            ends = [index for value in (b"\n", b"\r") if (index := self.pending.find(value)) >= 0]
            if not ends:
                return
            end = min(ends)
            self._progress(bytes(self.pending[:end]))
            del self.pending[: end + 1]

    def _progress(self, line):
        match = _TIME_RE.search(line.decode("utf-8", errors="replace"))
        if match:
            percent = min(100.0, self.parse_time(match.group(1)) / self.duration * 100)
            self.callback(percent)


def run_progress(
    cmd: list[str],
    duration: float,
    callback: Callable[[float], None],
    parse_time,
    *,
    pass_fds=(),
    timeout=DEFAULT_FFMPEG_TIMEOUT,
):
    """Do not return from cancellation while an owned process can still write."""
    # Controlled argv from the runtime resolver; never execute a shell.
    kwargs = {"pass_fds": pass_fds} if pass_fds else {}
    proc = subprocess.Popen(  # noqa: S603
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs
    )
    diagnostics = _Diagnostics(proc, duration, callback, parse_time)
    reader = threading.Thread(target=diagnostics.read, name="kinocut-ffmpeg-progress")
    started = False
    try:
        reader.start()
        started = True
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ProcessingError(" ".join(cmd), -1, f"FFmpeg command timed out after {timeout}s") from None
    except BaseException:
        _stop(proc)
        raise
    finally:
        if started:
            reader.join(timeout=DEFAULT_FFMPEG_PROGRESS_READER_JOIN_TIMEOUT)
        if proc.stderr is not None and not reader.is_alive():
            proc.stderr.close()
    if reader.is_alive():
        raise ProcessingError(" ".join(cmd), -1, "FFmpeg diagnostic reader did not stop")
    if diagnostics.errors:
        raise diagnostics.errors[0]
    stderr = diagnostics.prefix.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise parse_ffmpeg_error(stderr, command=cmd)
    callback(100.0)
    return subprocess.CompletedProcess(cmd, proc.returncode, "", stderr)
