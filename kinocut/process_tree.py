"""Owned subprocess sessions or Windows Jobs, including descendant cleanup."""

import contextlib
import os
import signal
import subprocess
import threading
import time

from .defaults import DEFAULT_RENDER_STOP_POLL_INTERVAL, DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError, ProcessingError


class ProcessTree:
    def __init__(
        self, cmd: list[str], *, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds: tuple[int, ...] = ()
    ):
        from .process_windows import CREATE_SUSPENDED, WindowsJob

        from .process_guardian_owner import prepare_guardian

        self.guardian = prepare_guardian(cmd, pass_fds)
        if self.guardian is not None:
            cmd, pass_fds = self.guardian.cmd, self.guardian.pass_fds
        self.job = WindowsJob() if os.name == "nt" else None
        self.process = None
        self.lock = threading.Lock()
        self.closed = False
        self.exitcode: int | None = None
        self.command = cmd
        try:
            # Popen has no timeout; caller owns a deadline and waits with a timeout.
            self.process = subprocess.Popen(  # noqa: S603 - trusted argv, no shell.
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=os.name == "posix",
                creationflags=CREATE_SUSPENDED if os.name == "nt" else 0,
                pass_fds=pass_fds,
            )
            if self.job is not None:
                self.job.attach(self.process)
            if self.guardian is not None:
                self.guardian.wait_exec()
        except BaseException as exc:
            try:
                if self.process is not None:
                    if os.name == "nt":
                        self.process.kill()  # Windows handle remains stable if Job assignment failed.
                    if self.guardian is not None and self.guardian.retaining:
                        self.guardian.request_stop()
                    self.close()
            finally:
                if self.guardian is not None:
                    self.guardian.close()
                if self.job is not None:
                    self.job.close()
                if self.process is not None:
                    for pipe in (self.process.stdout, self.process.stderr):
                        if pipe is not None:
                            pipe.close()
            if isinstance(exc, OSError):
                raise ProcessingError("command launch", -1, "Command backend could not start") from None
            raise

    def wait(self, timeout: float | None = None) -> int:
        """Observe completion without relinquishing POSIX group authority."""
        from .process_observation import observe_exit

        process = self.process
        if process is None:
            raise MCPVideoError("Owned child is unavailable", code="process_ownership_unavailable")
        if os.name != "posix":
            return process.wait(timeout=timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self.lock:
                if self.closed:
                    result = self.exitcode if self.exitcode is not None else process.returncode
                    if result is None:
                        raise MCPVideoError("Owned child status is unavailable", code="process_ownership_unavailable")
                    return result
                if process.returncode is not None:
                    raise MCPVideoError("Owned child was reaped outside cleanup", code="process_ownership_unavailable")
                if self.exitcode is None:
                    self.exitcode = (
                        self.guardian.observe_status()
                        if self.guardian is not None and self.guardian.retaining
                        else observe_exit(self.process)
                    )
                if self.exitcode is not None:
                    return self.exitcode
            remaining = None if deadline is None else deadline - time.monotonic()
            if timeout is not None and remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(self.command, timeout)
            time.sleep(
                DEFAULT_RENDER_STOP_POLL_INTERVAL
                if remaining is None
                else min(DEFAULT_RENDER_STOP_POLL_INTERVAL, remaining)
            )

    def _kill(self):
        if self.process is None:
            return
        if self.job is not None:
            self.job.stop()
        elif self.guardian is not None and self.guardian.retaining:
            if self.guardian.alive_write not in self.guardian.descriptors:
                return
            try:
                pid, status = os.waitpid(self.process.pid, os.WNOHANG)
            except ChildProcessError as exc:
                raise MCPVideoError(
                    "Owned supervisor was reaped outside cleanup", code="process_ownership_unavailable"
                ) from exc
            if pid:
                self.process.returncode = os.waitstatus_to_exitcode(status)
                raise MCPVideoError("Owned supervisor exited before cleanup", code="process_ownership_unavailable")
            self.guardian.request_stop()
        else:
            from .process_observation import observe_exit

            observe_exit(self.process)
            if self.process.returncode is not None:
                raise MCPVideoError("Owned child was reaped outside cleanup", code="process_ownership_unavailable")
            with contextlib.suppress(ProcessLookupError):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except PermissionError as exc:
                    raise MCPVideoError("Owned group cleanup was denied", code="process_cleanup_failed") from exc

    def kill(self):
        with self.lock:
            if not self.closed:
                self._kill()

    def close(self):
        with self.lock:
            if self.closed or self.process is None:
                return
            interrupted, failure = False, None
            try:
                while True:
                    try:
                        self._kill()
                        break
                    except KeyboardInterrupt:
                        interrupted = True
                    except MCPVideoError as exc:
                        failure = exc
                        # Closing a Windows Job is also a kill operation.
                        if self.job is not None:
                            self.job.close()
                        break
                deadline = time.monotonic() + DEFAULT_RENDER_STOP_TIMEOUT
                while True:
                    try:
                        self.process.wait(timeout=max(0, deadline - time.monotonic()))
                        break
                    except KeyboardInterrupt:
                        interrupted = True
                    except subprocess.TimeoutExpired as exc:
                        raise MCPVideoError("Owned child could not be reaped", code="process_cleanup_failed") from exc
            finally:
                if self.guardian is not None:
                    self.guardian.close()
                if self.job is not None:
                    self.job.close()
                self.closed = True
            if failure is not None:
                raise failure
            if interrupted:
                raise KeyboardInterrupt
