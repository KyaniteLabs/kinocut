"""Own the process registry and cleanup policy for Hyperframes previews."""

from __future__ import annotations

import atexit
import os
import signal
import subprocess

_active_previews: dict[int, subprocess.Popen[str]] = {}


def _register_preview(port: int, proc: subprocess.Popen[str]) -> None:
    """Track a running preview process so it can be terminated later."""
    old = _active_previews.get(port)
    if old is not None and old.poll() is None:
        stop_preview(port)
    _active_previews[port] = proc


def _terminate_preview(proc: subprocess.Popen[str]) -> None:
    """Best-effort termination of a preview process and its child group."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        proc.wait(timeout=3)


def stop_preview(port: int) -> bool:
    """Terminate the preview server on *port*. Returns True if a process was stopped."""
    proc = _active_previews.pop(port, None)
    if proc is None:
        return False
    _terminate_preview(proc)
    return True


def release_preview(port: int, pid: int | None) -> None:
    """Transfer a CLI preview to the caller without terminating its server."""
    proc = _active_previews.get(port)
    if proc is None or proc.pid != pid or proc.poll() is not None:
        raise RuntimeError("Preview process is no longer owned or running")
    del _active_previews[port]


def stop_all_previews() -> None:
    """Terminate every running preview server (called automatically at exit)."""
    for port in list(_active_previews):
        proc = _active_previews.pop(port, None)
        if proc is not None:
            _terminate_preview(proc)


atexit.register(stop_all_previews)
