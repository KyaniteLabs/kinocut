"""Private detached-worker lease binding and bounded guardian startup."""

from __future__ import annotations

import contextlib
import errno
import os
import select
import sys
import time
from pathlib import Path

from .defaults import DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError
from .limits import MAX_PROCESS_GUARDIAN_ERROR_BYTES

_WORKER_OWNER: tuple[int, int, int, int] | None = None
_PARENT_WRITERS: set[int] = set()


def _close_forked_writers():
    # A forked sibling must not retain another command's parent-liveness writer.
    # No locks/imports are used after fork; Popen also closes unpassed descriptors.
    for descriptor in tuple(_PARENT_WRITERS):
        with contextlib.suppress(OSError):
            os.close(descriptor)
    _PARENT_WRITERS.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_close_forked_writers)


@contextlib.contextmanager
def bind_worker_lease(descriptor: int):
    """Enable only for the actual dedicated, lease-owning worker process."""
    global _WORKER_OWNER
    if os.name != "posix":
        yield
        return
    if _WORKER_OWNER is not None or os.getsid(0) != os.getpid() or descriptor < 3:
        raise MCPVideoError("Detached worker ownership is invalid", code="process_ownership_unavailable")
    stat = os.fstat(descriptor)
    _WORKER_OWNER = (os.getpid(), descriptor, stat.st_dev, stat.st_ino)
    try:
        yield
    finally:
        _WORKER_OWNER = None


class Guardian:
    def __init__(
        self, cmd: list[str], pass_fds: tuple[int, ...], owner: tuple[int, int | None, int | None, int | None]
    ):
        self.descriptors = set()
        try:
            parent, descriptor, device, inode = owner
            stat = os.fstat(descriptor) if descriptor is not None else None
            if stat is not None and (stat.st_dev, stat.st_ino) != (device, inode):
                raise MCPVideoError("Detached worker lease changed", code="process_ownership_unavailable")
            self.lease = os.dup(descriptor) if descriptor is not None else -1
            if self.lease >= 0:
                self.descriptors.add(self.lease)
            self.alive_read, self.alive_write = os.pipe()
            self.descriptors.update((self.alive_read, self.alive_write))
            self.error_read, self.error_write = os.pipe()
            self.descriptors.update((self.error_read, self.error_write))
            _PARENT_WRITERS.add(self.alive_write)
            from .process_observation import supports_nonreaping_wait

            self.retaining = not supports_nonreaping_wait()
            self.status_read, self.status_write = os.pipe() if self.retaining else (-1, -1)
            if self.retaining:
                self.descriptors.update((self.status_read, self.status_write))
            native_descriptors: set[int] = set(pass_fds)
            if self.lease >= 0:
                native_descriptors.add(self.lease)
            native_fds = tuple(sorted(native_descriptors))
            self.pass_fds: tuple[int, ...] = (
                *native_fds,
                self.alive_read,
                self.error_write,
                *([self.status_write] if self.retaining else []),
            )
            self.cmd = [
                sys.executable,
                "-I",
                "-S",
                str(Path(__file__).with_name("process_guardian.py")),
                str(parent),
                str(self.alive_read),
                str(self.error_write),
                str(self.lease),
                ",".join(map(str, native_fds)),
                str(self.status_write),
                "--",
                *cmd,
            ]
            self.native_cmd = cmd
        except BaseException:
            self.close()
            raise

    def _close(self, descriptor):
        if descriptor in self.descriptors:
            self.descriptors.remove(descriptor)
            _PARENT_WRITERS.discard(descriptor)
            os.close(descriptor)

    def wait_exec(self):
        for descriptor in (self.alive_read, self.error_write, self.lease, self.status_write):
            self._close(descriptor)
        deadline, error = time.monotonic() + DEFAULT_RENDER_STOP_TIMEOUT, bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.error_read], [], [], max(0, remaining))[0]:
                raise MCPVideoError("Owned command startup timed out", code="process_ownership_unavailable")
            chunk = os.read(self.error_read, MAX_PROCESS_GUARDIAN_ERROR_BYTES + 1 - len(error))
            if not chunk:
                break
            error.extend(chunk)
            if len(error) > MAX_PROCESS_GUARDIAN_ERROR_BYTES:
                raise MCPVideoError(
                    "Owned command startup response exceeded its limit", code="process_ownership_unavailable"
                )
        self._close(self.error_read)
        if error == b"R":
            return
        payload = bytes(error).removeprefix(b"R")
        if payload.startswith(b"E") and payload[1:].isdigit():
            raise OSError(int(payload[1:]) or errno.EIO, "Owned command could not start", self.native_cmd[0])
        raise MCPVideoError("Owned command startup failed", code="process_ownership_unavailable")

    def request_stop(self):
        """EOF asks the live supervisor to signal only its own held group."""
        self._close(self.alive_write)

    def observe_status(self) -> int | None:
        if not select.select([self.status_read], [], [], 0)[0]:
            return None
        data = os.read(self.status_read, MAX_PROCESS_GUARDIAN_ERROR_BYTES + 1)
        if len(data) > MAX_PROCESS_GUARDIAN_ERROR_BYTES or not data.startswith(b"C"):
            raise MCPVideoError("Owned command status is invalid", code="process_ownership_unavailable")
        payload = data[1:]
        if not payload or not payload.removeprefix(b"-").isdigit():
            raise MCPVideoError("Owned command status is invalid", code="process_ownership_unavailable")
        result = int(payload)
        if not -255 <= result <= 255:
            raise MCPVideoError("Owned command status is invalid", code="process_ownership_unavailable")
        self._close(self.status_read)
        return result

    def close(self):
        for descriptor in tuple(self.descriptors):
            with contextlib.suppress(OSError):
                self._close(descriptor)


def prepare_guardian(cmd: list[str], pass_fds: tuple[int, ...]):
    from .process_observation import supports_nonreaping_wait

    owner = _WORKER_OWNER
    if os.name != "posix":
        return None
    if owner is not None and owner[0] != os.getpid():
        owner = None
    if owner is None and supports_nonreaping_wait():
        return None
    return Guardian(cmd, pass_fds, owner or (os.getpid(), None, None, None))
