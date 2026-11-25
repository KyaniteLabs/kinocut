"""Owned subprocess sessions or Windows Jobs, including descendant cleanup.

POSIX commands always run under process_guardian so a SIGKILLed owner cannot
leave a detached encoder. The guardian watches the owner-liveness pipe and
kills its own session on EOF. Windows still uses kill-on-close Job Objects.
Clean SIGTERM/SIGHUP paths keep ProcessTree.close() / killpg as before.
"""

import contextlib
import os
import selectors
import signal
import subprocess
import threading
import time

from .defaults import DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError, ProcessingError

_SENSITIVE_SUBPROCESS_ENV_VARS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "KINOCUT_VISION_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "HF_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITLAB_TOKEN",
        "NPM_TOKEN",
        "NODE_AUTH_TOKEN",
        "NODE_OPTIONS",
        "PYPI_TOKEN",
        "TWINE_PASSWORD",
    }
)
_SENSITIVE_SUBPROCESS_ENV_SUFFIXES = (
    "_API_KEY",
    "_SECRET_KEY",
    "_ACCESS_TOKEN",
    "_AUTH_TOKEN",
    "_PRIVATE_KEY",
)
_PROXY_ENV_VARS = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"})


def sanitized_subprocess_env(
    base_env: dict[str, str] | None = None,
    *,
    extra: dict[str, str] | None = None,
    strip_proxies: bool = False,
) -> dict[str, str]:
    """Return a subprocess environment with ambient credentials and injection vars scrubbed."""
    source = os.environ if base_env is None else base_env
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper in _SENSITIVE_SUBPROCESS_ENV_VARS:
            continue
        if strip_proxies and upper in _PROXY_ENV_VARS:
            continue
        if any(upper.endswith(suffix) for suffix in _SENSITIVE_SUBPROCESS_ENV_SUFFIXES):
            continue
        cleaned[key] = value
    if extra:
        cleaned.update(extra)
    return cleaned


class ProcessTree:
    """One owned command and all its descendants.

    Lifecycle (``wait``, ``kill`` and ``close`` hold ``lock``):

    - ``__init__`` launches, or cleans up and raises; a half-built tree never
      reaches the caller.
    - Open: ``wait`` caches the first exit status it observes in ``exitcode``;
      ``kill`` stops the tree and keeps ownership.
    - ``close`` (idempotent) kills, reaps within ``DEFAULT_RENDER_STOP_TIMEOUT``,
      releases the guardian or Job and sets ``closed``. Afterwards ``wait``
      returns the recorded status (or raises if none was recorded) and
      ``kill`` does nothing.

    Losing ownership (the child or supervisor reaped by someone else) is not a
    state: it raises ``process_ownership_unavailable``. The rest of the state
    lives in ``process.returncode`` and ``guardian.retaining``, owned by Popen
    and the guardian, so there is deliberately no phase field mirroring it.
    """

    def __init__(
        self,
        cmd: list[str],
        *,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds: tuple[int, ...] = (),
        env: dict[str, str] | None = None,
    ):
        from .offline import offline_media_command
        from .process_windows import CREATE_SUSPENDED, WindowsJob

        from .process_guardian_owner import prepare_guardian

        cmd = offline_media_command(cmd)
        self.guardian = prepare_guardian(cmd, pass_fds)
        if self.guardian is not None:
            cmd, pass_fds = self.guardian.cmd, self.guardian.pass_fds
        self.job = WindowsJob() if os.name == "nt" else None
        self.process = None
        self.lock = threading.Lock()
        self.closed = False
        self.exitcode: int | None = None
        self._exit_event: threading.Event | None = None
        self._exit_thread: threading.Thread | None = None
        self.command = cmd
        child_env = sanitized_subprocess_env(env)
        try:
            # Popen has no timeout; caller owns a deadline and waits with a timeout.
            self.process = subprocess.Popen(  # noqa: S603 - trusted argv, no shell.
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=child_env,
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
                raise ProcessingError("command launch", -1, "", reason="Command backend could not start") from None
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
                if remaining is not None and remaining <= 0:
                    raise subprocess.TimeoutExpired(self.command, timeout)
                descriptor = None
                if self.guardian is not None and self.guardian.retaining:
                    descriptor = os.dup(self.guardian.status_read)
                else:
                    event = self._native_exit_event(process.pid)
            if descriptor is None:
                ready = event.wait(remaining)
            else:
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(descriptor, selectors.EVENT_READ)
                        ready = bool(selector.select(remaining))
                finally:
                    os.close(descriptor)
            if not ready:
                raise subprocess.TimeoutExpired(self.command, timeout)

    def _native_exit_event(self, pid: int) -> threading.Event:
        """One non-reaping observer shared by timed waits and concurrent waiters."""
        if self._exit_event is None:
            event = threading.Event()

            def observe():
                try:
                    os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
                except OSError:
                    pass  # wait() checks ownership again under the lock.
                finally:
                    event.set()

            thread = threading.Thread(target=observe, daemon=True)
            thread.start()
            self._exit_thread = thread
            self._exit_event = event
        return self._exit_event

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
                if self._exit_thread is not None and self._exit_thread is not threading.current_thread():
                    self._exit_thread.join(timeout=DEFAULT_RENDER_STOP_TIMEOUT)
                self.closed = True
            if failure is not None:
                raise failure
            if interrupted:
                raise KeyboardInterrupt
