"""Owned FFmpeg progress process with bounded chunk diagnostics and cancellation."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable

from .bounded_process import run_bounded
from .errors import ProcessingError, parse_ffmpeg_error
from .limits import DEFAULT_FFMPEG_TIMEOUT, FFMPEG_PROGRESS_LINE_BYTES, FFMPEG_PROGRESS_STDERR_BYTES
from .limits import resolve_ffmpeg_timeout

_TIME_RE = re.compile(r"time=(\d+:\d+:\d+\.\d+)")


class _Diagnostics:
    def __init__(self, duration: float, callback: Callable[[float], None], parse_time: Callable[[str], float]):
        self.duration, self.callback, self.parse_time = duration, callback, parse_time
        self.head_limit = FFMPEG_PROGRESS_STDERR_BYTES // 2
        self.tail_limit = FFMPEG_PROGRESS_STDERR_BYTES - self.head_limit
        self.prefix, self.tail, self.pending = bytearray(), bytearray(), bytearray()
        self.callback_error: BaseException | None = None

    def write(self, chunk: memoryview, /) -> int:
        space = max(0, self.head_limit - len(self.prefix))
        self.prefix.extend(chunk[:space])
        self.tail.extend(chunk[space:])
        if len(self.tail) > self.tail_limit:
            del self.tail[: -self.tail_limit]
        self.pending.extend(chunk)
        self._lines()
        if len(self.pending) > FFMPEG_PROGRESS_LINE_BYTES:
            del self.pending[:-FFMPEG_PROGRESS_LINE_BYTES]
        return len(chunk)

    def flush(self) -> None:
        self._progress(bytes(self.pending))

    def captured_stderr(self) -> str:
        raw = bytes(self.prefix) + bytes(self.tail)
        return raw.decode("utf-8", errors="replace")

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
            try:
                self.callback(percent)
            except BaseException as exc:
                self.callback_error = exc
                raise


def run_progress(
    cmd: list[str],
    duration: float,
    callback: Callable[[float], None],
    parse_time: Callable[[str], float],
    *,
    pass_fds: tuple[int, ...] = (),
    timeout: float | None = None,
    default_timeout: float = DEFAULT_FFMPEG_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Do not return from cancellation while an owned process can still write."""
    diagnostics = _Diagnostics(duration, callback, parse_time)
    effective_timeout = resolve_ffmpeg_timeout(timeout, default=default_timeout)
    try:
        result = run_bounded(
            cmd, timeout=effective_timeout, pass_fds=pass_fds, discard_stdout=True, stderr_sink=diagnostics
        )
    except subprocess.TimeoutExpired as exc:
        if exc is diagnostics.callback_error:
            raise
        raise ProcessingError(
            " ".join(cmd), -1, "", reason=f"FFmpeg command timed out after {effective_timeout}s"
        ) from None
    result.stderr = diagnostics.captured_stderr()
    if result.returncode != 0:
        raise parse_ffmpeg_error(result.stderr, command=cmd)
    callback(100.0)
    return result
