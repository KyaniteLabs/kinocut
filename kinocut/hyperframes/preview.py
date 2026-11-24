"""Start, verify, and clean up local Hyperframes preview processes."""

from __future__ import annotations

import atexit
import subprocess
import time
from pathlib import Path

from ..errors import HyperframesProjectError
from .models import HyperframesPreviewResult
from .runner import (
    _hyperframes_command_prefix,
    _hyperframes_environment,
    _require_hyperframes_deps,
    _require_node,
    _require_private_preview,
    current_runner,
    PreviewChild,
    terminate_process_group,
)
from .validation import _validate_project


_POPEN_TYPE = subprocess.Popen
_active_previews: dict[int, PreviewChild | subprocess.Popen[str]] = {}


def _register_preview(port: int, proc: PreviewChild | subprocess.Popen[str]) -> None:
    """Track a running preview process so it can be terminated later."""
    old = _active_previews.get(port)
    if old is not None and old.poll() is None:
        stop_preview(port)
    _active_previews[port] = proc


def _terminate_preview(proc: PreviewChild | subprocess.Popen[str]) -> None:
    """Best-effort termination of a preview process and its child group."""
    if isinstance(proc, _POPEN_TYPE):
        terminate_process_group(proc)
    else:
        proc.stop()


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


def _preview_ready(port: int, project: Path, pid: int) -> bool:
    return current_runner().preview_ready(port, project, pid)


def preview(
    project_path: str,
    port: int = 3002,
    startup_timeout: int = 10,
) -> HyperframesPreviewResult:
    """Launch Hyperframes preview studio (non-blocking)."""
    if port < 1024 or port > 65535:
        raise HyperframesProjectError(str(project_path), "Preview port must be between 1024 and 65535")
    _require_node()
    project, _entry_point = _validate_project(project_path)
    _require_hyperframes_deps(cwd=project)
    _require_private_preview(project)
    stop_preview(port)

    cmd = [
        *_hyperframes_command_prefix(cwd=project),
        "preview",
        str(project),
        "--port",
        str(port),
        "--foreground",
        "--no-open",
        "--force-new",
    ]
    env = _hyperframes_environment()
    env["HYPERFRAMES_PREVIEW_HOST"] = "127.0.0.1"
    proc = current_runner().start_preview(cmd, cwd=project, env=env)

    try:
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise HyperframesProjectError(str(project), "Hyperframes preview exited immediately")
            if _preview_ready(port, project, proc.pid) and proc.poll() is None:
                break
            time.sleep(0.1)
        else:
            raise HyperframesProjectError(str(project), "Hyperframes preview did not start on the requested port")
    except BaseException:
        _terminate_preview(proc)
        raise
    _register_preview(port, proc)

    return HyperframesPreviewResult(
        url=f"http://localhost:{port}",
        port=port,
        project_path=str(project),
        pid=proc.pid,
    )
