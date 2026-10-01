"""Owned subprocess sessions or Windows Jobs, including descendant cleanup."""

import contextlib
import os
import signal
import subprocess
import threading
import time

from .defaults import DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError


class ProcessTree:
    def __init__(self, cmd, *, stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=()):
        from .process_windows import CREATE_SUSPENDED, WindowsJob

        from .process_guardian_owner import prepare_guardian

        self.guardian = prepare_guardian(cmd, pass_fds)
        if self.guardian is not None:
            cmd, pass_fds = self.guardian.cmd, self.guardian.pass_fds
        self.job = WindowsJob() if os.name == "nt" else None
        self.process = None
        self.lock = threading.Lock()
        self.closed = False
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
        except BaseException:
            try:
                if self.process is not None:
                    with contextlib.suppress(ProcessLookupError):
                        self.process.kill()
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
            raise

    def _kill(self):
        if self.process is None:
            return
        if self.job is not None:
            self.job.stop()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)

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
