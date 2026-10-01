"""Bounded subprocess pipe draining with owned process-tree cleanup."""

from __future__ import annotations

import subprocess
import threading
from typing import BinaryIO, Literal, overload

from .defaults import DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError
from .limits import MAX_SUBPROCESS_STDERR_BYTES, MAX_SUBPROCESS_STDOUT_BYTES, SUBPROCESS_READ_CHUNK_BYTES
from .process_tree import ProcessTree


def output_limit_error(stream: str) -> MCPVideoError:
    return MCPVideoError(
        f"Command {stream} exceeded its byte limit",
        error_type="processing_error",
        code=f"command_{stream}_limit_exceeded",
    )


class _Drain:
    def __init__(self, tree, stream, limit, sink):
        self.tree, self.stream, self.limit, self.sink = tree, stream, limit, sink
        self.buffer, self.errors, self.count = bytearray(), [], 0
        self.thread = threading.Thread(target=self.read, name=f"kinocut-command-{stream}")

    def read(self):
        pipe = getattr(self.tree.process, self.stream)
        try:
            while chunk := pipe.read1(SUBPROCESS_READ_CHUNK_BYTES):
                if self.count + len(chunk) > self.limit:
                    raise output_limit_error(self.stream)
                self.count += len(chunk)
                if self.sink is None:
                    self.buffer.extend(chunk)
                else:
                    self._write(chunk)
            if self.sink is not None:
                self.sink.flush()
        except BaseException as exc:
            self.errors.append(exc)
            self.tree.kill()

    def _write(self, chunk):
        remaining = memoryview(chunk)
        while remaining:
            written = self.sink.write(remaining)
            if type(written) is not int or not 0 < written <= len(remaining):
                raise MCPVideoError("Command output sink could not be written", code="command_sink_failed")
            remaining = remaining[written:]

    @overload
    def result(self, text: Literal[True]) -> str | None: ...

    @overload
    def result(self, text: Literal[False]) -> bytes | None: ...

    def result(self, text: bool) -> str | bytes | None:
        if self.sink is not None:
            return None
        return self.buffer.decode("utf-8", errors="replace") if text else bytes(self.buffer)


@overload
def run_bounded(
    cmd: list[str],
    *,
    timeout: float,
    text: Literal[True] = True,
    pass_fds: tuple[int, ...] = (),
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
    stderr_limit: int = MAX_SUBPROCESS_STDERR_BYTES,
) -> subprocess.CompletedProcess[str]: ...


@overload
def run_bounded(
    cmd: list[str],
    *,
    timeout: float,
    text: Literal[False],
    pass_fds: tuple[int, ...] = (),
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
    stderr_limit: int = MAX_SUBPROCESS_STDERR_BYTES,
) -> subprocess.CompletedProcess[bytes]: ...


@overload
def run_bounded(
    cmd: list[str],
    *,
    timeout: float,
    text: bool,
    pass_fds: tuple[int, ...] = (),
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
    stderr_limit: int = MAX_SUBPROCESS_STDERR_BYTES,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]: ...


def run_bounded(
    cmd: list[str],
    *,
    timeout: float,
    text: bool = True,
    pass_fds: tuple[int, ...] = (),
    stdout_sink: BinaryIO | None = None,
    stderr_sink: BinaryIO | None = None,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
    stderr_limit: int = MAX_SUBPROCESS_STDERR_BYTES,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Never return partial captured payloads as successful command output."""
    for limit in (stdout_limit, stderr_limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise MCPVideoError("Command byte limits must be positive integers", code="invalid_command_limit")
    tree = ProcessTree(cmd, pass_fds=pass_fds)
    process = tree.process
    if process is None:
        raise MCPVideoError("Owned child was not created", code="process_ownership_unavailable")
    drains = [_Drain(tree, "stdout", stdout_limit, stdout_sink), _Drain(tree, "stderr", stderr_limit, stderr_sink)]
    started = []
    try:
        for drain in drains:
            drain.thread.start()
            started.append(drain)
        returncode = process.wait(timeout=timeout)
    finally:
        # Kill surviving descendants even when their leader exited successfully:
        # inherited pipes must not keep drainers alive beyond the command lifetime.
        try:
            tree.close()
        finally:
            for drain in started:
                drain.thread.join(timeout=DEFAULT_RENDER_STOP_TIMEOUT)
            for pipe in (process.stdout, process.stderr):
                if pipe is not None and not any(d.thread.is_alive() for d in started):
                    pipe.close()
    for drain in drains:
        if drain.thread.is_alive():
            raise MCPVideoError("Command pipe reader did not stop", code="process_cleanup_failed")
        if drain.errors:
            raise drain.errors[0]
    if text:
        return subprocess.CompletedProcess(cmd, returncode, drains[0].result(True), drains[1].result(True))
    return subprocess.CompletedProcess(cmd, returncode, drains[0].result(False), drains[1].result(False))
