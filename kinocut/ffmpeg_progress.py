"""Owned FFmpeg progress process with bounded chunk diagnostics and cancellation."""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable

from .defaults import DEFAULT_FFMPEG_PROGRESS_READER_JOIN_TIMEOUT
from .errors import ProcessingError, parse_ffmpeg_error
from .bounded_process import output_limit_error
from .process_tree import ProcessTree
from .limits import (
    DEFAULT_FFMPEG_TIMEOUT,
    MAX_SUBPROCESS_STDERR_BYTES,
    FFMPEG_PROGRESS_LINE_BYTES,
    FFMPEG_PROGRESS_READ_BYTES,
    FFMPEG_PROGRESS_STDERR_BYTES,
)

_TIME_RE = re.compile(r"time=(\d+:\d+:\d+\.\d+)")


class _Diagnostics:
    def __init__(self, tree, duration, callback, parse_time):
        self.tree, self.proc, self.duration, self.callback, self.parse_time = (
            tree,
            tree.process,
            duration,
            callback,
            parse_time,
        )
        self.total = 0
        self.prefix, self.pending, self.errors = bytearray(), bytearray(), []

    def read(self):
        try:
            while self.proc.stderr is not None:
                chunk = self.proc.stderr.read1(FFMPEG_PROGRESS_READ_BYTES)
                if not chunk:
                    break
                self.total += len(chunk)
                if self.total > MAX_SUBPROCESS_STDERR_BYTES:
                    raise output_limit_error("stderr")
                space = FFMPEG_PROGRESS_STDERR_BYTES - len(self.prefix)
                self.prefix.extend(chunk[: max(0, space)])
                self.pending.extend(chunk)
                self._lines()
                if len(self.pending) > FFMPEG_PROGRESS_LINE_BYTES:
                    del self.pending[:-FFMPEG_PROGRESS_LINE_BYTES]
            self._progress(bytes(self.pending))
        except BaseException as exc:
            self.errors.append(exc)
            self.tree.kill()

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
    tree = ProcessTree(cmd, stdout=subprocess.DEVNULL, pass_fds=pass_fds)
    proc = tree.process
    diagnostics = _Diagnostics(tree, duration, callback, parse_time)
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
        tree.close()
        raise
    finally:
        tree.close()
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
