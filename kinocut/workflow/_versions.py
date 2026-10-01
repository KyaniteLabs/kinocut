"""Shared version helpers for workflow artifacts.

The plan artifact (``planner``) and the render receipt (``executor``) must both
report the identical ``versions`` object (tool + FFmpeg). This module owns the
single source of truth so the two artifacts can never drift apart.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..errors import MCPVideoError

from .. import __version__ as _MCP_VIDEO_VERSION

# Single source of truth for the determinism caveat every workflow artifact
# (plan + render receipt) records, so the two can never drift apart.
RENDER_DETERMINISM_SCOPE = "spec/input/output hashes are deterministic; rendered bytes may vary across FFmpeg builds"

_ffmpeg_version_cache: tuple[tuple, str] | None = None


def mcp_video_version() -> str:
    """Return the live installed Kinocut package version."""
    return _MCP_VIDEO_VERSION


def _binary_identity(executable: str) -> tuple | None:
    """Identify the observed executable; stat metadata is not a content digest."""
    try:
        path = Path(executable).resolve()
        stat = path.stat()
        return (str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except (OSError, RuntimeError):
        return None


def ffmpeg_version(executable: str | None = None) -> str | None:
    """Probe the selected FFmpeg version, caching only unchanged successful probes.

    The default uses the engine's configured executable; an explicit path keeps
    capability discovery's injected resolver and version evidence aligned.
    """
    from ..engine_runtime_utils import _ffmpeg

    global _ffmpeg_version_cache
    try:
        selected = executable if executable is not None else _ffmpeg()
        identity = _binary_identity(selected)
        if identity is None:
            return None
        if _ffmpeg_version_cache is not None and _ffmpeg_version_cache[0] == identity:
            return _ffmpeg_version_cache[1]
        result = subprocess.run(  # noqa: S603
            [selected, "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (MCPVideoError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or _binary_identity(selected) != identity:
        return None
    first_line = (result.stdout or result.stderr or "").splitlines()[:1]
    match = re.search(r"ffmpeg version (\S+)", first_line[0], re.IGNORECASE) if first_line else None
    if match:
        _ffmpeg_version_cache = (identity, match.group(1))
        return match.group(1)
    return None


def versions() -> dict[str, str | None]:
    """Return the shared ``{mcp_video, ffmpeg}`` versions object for artifacts."""
    return {"mcp_video": mcp_video_version(), "ffmpeg": ffmpeg_version()}
