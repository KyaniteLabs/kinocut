"""Bounded subprocess pipe draining with owned process-tree cleanup."""

from __future__ import annotations

import subprocess
import threading
from typing import Literal, Protocol, overload

from .defaults import DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError
from .limits import MAX_SUBPROCESS_STDERR_BYTES, MAX_SUBPROCESS_STDOUT_BYTES, SUBPROCESS_READ_CHUNK_BYTES
from .process_tree import ProcessTree


#: The stream's own name. The label is ours, so the message can name it.
_STREAM_LABELS = {"stdout": "standard output", "stderr": "standard error"}


class _PipeSink(Protocol):
    def write(self, chunk: memoryview, /) -> int: ...

    def flush(self) -> None: ...


def output_limit_error(stream: str) -> MCPVideoError:
    return MCPVideoError(
        f"Command {_STREAM_LABELS.get(stream, 'output')} exceeded its byte limit",
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
            try:
                self.tree.kill()
            except BaseException as cleanup:
                self.errors.append(cleanup)

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
    stdout_sink: _PipeSink | None = None,
    stderr_sink: _PipeSink | None = None,
    discard_stdout: bool = False,
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
    stdout_sink: _PipeSink | None = None,
    stderr_sink: _PipeSink | None = None,
    discard_stdout: bool = False,
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
    stdout_sink: _PipeSink | None = None,
    stderr_sink: _PipeSink | None = None,
    discard_stdout: bool = False,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
    stderr_limit: int = MAX_SUBPROCESS_STDERR_BYTES,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]: ...


def run_bounded(
    cmd: list[str],
    *,
    timeout: float,
    text: bool = True,
    pass_fds: tuple[int, ...] = (),
    stdout_sink: _PipeSink | None = None,
    stderr_sink: _PipeSink | None = None,
    discard_stdout: bool = False,
    stdout_limit: int = MAX_SUBPROCESS_STDOUT_BYTES,
    stderr_limit: int = MAX_SUBPROCESS_STDERR_BYTES,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    """Never return partial captured payloads as successful command output."""
    for limit in (stdout_limit, stderr_limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise MCPVideoError("Command byte limits must be positive integers", code="invalid_command_limit")
    if discard_stdout and stdout_sink is not None:
        raise ValueError("Cannot discard standard output and write it to a sink")
    tree = ProcessTree(cmd, stdout=subprocess.DEVNULL if discard_stdout else subprocess.PIPE, pass_fds=pass_fds)
    process = tree.process
    if process is None:
        raise MCPVideoError("Owned child was not created", code="process_ownership_unavailable")
    stdout = None if discard_stdout else _Drain(tree, "stdout", stdout_limit, stdout_sink)
    stderr = _Drain(tree, "stderr", stderr_limit, stderr_sink)
    drains = [stderr] if stdout is None else [stdout, stderr]
    started = []
    try:
        for drain in drains:
            drain.thread.start()
            started.append(drain)
        try:
            returncode = tree.wait(timeout=timeout)
        except MCPVideoError:
            for drain in drains:
                if drain.errors:
                    raise drain.errors[0] from None
            raise
    finally:
        # Kill surviving descendants even when their leader exited successfully:
        # inherited pipes must not keep drainers alive beyond the command lifetime.
        try:
            tree.close()
        finally:
            for drain in started:
                drain.thread.join(timeout=DEFAULT_RENDER_STOP_TIMEOUT)
            for drain in drains:
                if not drain.thread.is_alive():
                    getattr(process, drain.stream).close()
    for drain in drains:
        if drain.thread.is_alive():
            raise MCPVideoError("Command pipe reader did not stop", code="process_cleanup_failed")
        if drain.errors:
            raise drain.errors[0] from None
    if text:
        return subprocess.CompletedProcess(
            cmd, returncode, "" if stdout is None else stdout.result(True), stderr.result(True)
        )
    return subprocess.CompletedProcess(
        cmd, returncode, b"" if stdout is None else stdout.result(False), stderr.result(False)
    )
