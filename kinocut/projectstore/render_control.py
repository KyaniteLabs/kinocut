"""Bounded detached-render stop verification without trusting a stale PID alone."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import time
import threading
from pathlib import Path
from collections.abc import Callable

from kinocut.defaults import DEFAULT_RENDER_STOP_POLL_INTERVAL, DEFAULT_RENDER_STOP_TIMEOUT

CANCELLATION_REQUESTED = "cancellation_requested"
TERMINATION_REQUESTED = "termination_requested"
STOP_REQUEST_STAGES = frozenset({CANCELLATION_REQUESTED, TERMINATION_REQUESTED})
logger = logging.getLogger(__name__)


def group_quiescent(pid: int | None) -> bool:
    """Prove no executing group members; zombie processes cannot produce output."""
    if not isinstance(pid, int) or pid <= 1 or pid == os.getpid() or not hasattr(os, "getpgid"):
        return False
    try:
        if os.getpgid(pid) != pid:
            return False
    except ProcessLookupError:
        pass
    except OSError:
        return False
    if Path("/proc/self/stat").is_file():
        return _linux_group_quiescent(pid)
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _linux_group_quiescent(pgid: int) -> bool:
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            except FileNotFoundError:
                continue
            if int(fields[2]) == pgid and fields[0] not in {"Z", "X"}:
                return False
    except (OSError, ValueError, IndexError):
        return False
    return True


def stop_runner_group(pid: int | None, lease_is_held: Callable[[], bool]) -> str:
    """Wait for the worker to stop itself; never signal a reusable external PID.

    Running journal intent is consumed by the dedicated worker's self-stop
    watcher. Its command guardians retain the lease until descendants stop.
    Legacy or unresponsive workers remain unconfirmed rather than being killed
    on the strength of a stale PID and a possibly inherited lease.
    """
    if group_quiescent(pid) and not lease_is_held():
        return "stopped"
    if not isinstance(pid, int) or pid <= 1 or pid == os.getpid() or not hasattr(os, "getpgid"):
        return "identity_unverified"
    try:
        if os.getpgid(pid) != pid:
            return "identity_unverified"
    except ProcessLookupError:
        pass  # Guardians may still own the lease after their worker disappeared.
    except OSError:
        return "identity_unverified"
    if not lease_is_held():
        # Self-stop can finish between the first group check and this lease
        # check. Confirm that transition without signalling a reusable PID.
        return "stopped" if group_quiescent(pid) and not lease_is_held() else "identity_unverified"
    deadline = time.monotonic() + DEFAULT_RENDER_STOP_TIMEOUT
    while time.monotonic() < deadline:
        if group_quiescent(pid) and not lease_is_held():
            return "stopped"
        time.sleep(DEFAULT_RENDER_STOP_POLL_INTERVAL)
    return "timeout"


@contextlib.contextmanager
def watch_runner_stop(stop_requested: Callable[[], bool]):
    """Observe validated journal intent only inside the dedicated worker."""
    owner = os.getpid()
    finished = threading.Event()
    watcher = threading.Thread(
        target=_watch_stop_requests,
        args=(owner, finished, stop_requested),
        name="kinocut-render-stop",
        daemon=True,
    )
    watcher.start()
    try:
        yield
    finally:
        finished.set()
        watcher.join(timeout=DEFAULT_RENDER_STOP_TIMEOUT)
        if watcher.is_alive():
            from kinocut.errors import MCPVideoError

            raise MCPVideoError("Render stop watcher did not finish", code="process_cleanup_failed")


def _watch_stop_requests(owner: int, finished: threading.Event, stop_requested: Callable[[], bool]) -> None:
    warned = False
    while not finished.is_set():
        if os.getpid() != owner:  # Forked copies never acquire stop authority.
            return
        try:
            if stop_requested():
                if not _stop_current_runner(owner):
                    logger.warning("Render stop watcher could not verify its own private session")
                return
            warned = False
        except Exception as exc:
            if not warned:
                logger.warning("Render stop request could not be observed (%s)", type(exc).__name__)
                warned = True
        finished.wait(DEFAULT_RENDER_STOP_POLL_INTERVAL)


def _stop_current_runner(owner: int) -> bool:
    """A live executing owner pins its own PID/group against identifier reuse."""
    if os.getpid() != owner:
        return False
    if os.name == "posix":
        if os.getpgrp() != owner or os.getsid(0) != owner:
            return False
        os.killpg(owner, signal.SIGKILL)
        return True
    if os.name == "nt":
        os.kill(owner, signal.SIGTERM)
        return True
    return False
