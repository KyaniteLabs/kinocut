"""Bounded detached-render stop verification without trusting a stale PID alone."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from collections.abc import Callable

from kinocut.defaults import DEFAULT_RENDER_STOP_POLL_INTERVAL, DEFAULT_RENDER_STOP_TIMEOUT

CANCELLATION_REQUESTED = "cancellation_requested"
TERMINATION_REQUESTED = "termination_requested"
STOP_REQUEST_STAGES = frozenset({CANCELLATION_REQUESTED, TERMINATION_REQUESTED})


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
    """Signal only a verified session leader with its held job lease, then wait."""
    if group_quiescent(pid) and not lease_is_held():
        return "stopped"
    verified = isinstance(pid, int) and pid > 1 and pid != os.getpid() and hasattr(os, "getpgid")
    if verified:
        try:
            verified = pid != os.getpgrp() and os.getpgid(pid) == pid and lease_is_held()
        except OSError:
            verified = False
    if not verified:
        return "identity_unverified"
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        return "signal_failed"
    deadline = time.monotonic() + DEFAULT_RENDER_STOP_TIMEOUT
    while time.monotonic() < deadline:
        if group_quiescent(pid) and not lease_is_held():
            return "stopped"
        time.sleep(DEFAULT_RENDER_STOP_POLL_INTERVAL)
    return "timeout"
